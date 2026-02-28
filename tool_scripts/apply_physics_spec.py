"""apply_physics_spec.py — Annotate a USD stage with Isaac Sim (PhysX) physics.

What it does
------------
Reads a geometry-only ``robot.usda`` (from ``blender_export_usd.py``) and a
``physics_spec.json`` (from the physics_spec subagent), then writes a new
``robot_physics.usda`` with all ``UsdPhysics`` schemas applied so the asset can be
dropped straight into NVIDIA Isaac Sim.

It applies, in order:

1. Stage metadata: Z-up axis, meters-per-unit, ``/World`` default prim.
2. ``UsdPhysics.Scene`` with gravity.
3. Per rigid body: ``RigidBodyAPI`` + ``MassAPI`` on the link Xform,
   ``CollisionAPI`` + ``MeshCollisionAPI`` on each descendant mesh, and a bound
   physics ``MaterialAPI`` for friction/restitution.
4. Articulation root: a world ``FixedJoint`` (fixed-base) carrying
   ``ArticulationRootAPI``, or the API on the root Xform directly (free base).
5. Per joint: ``RevoluteJoint`` / ``PrismaticJoint`` / ``FixedJoint`` with body
   relationships, axis, limits, computed local frames (so bodies are not snapped
   together), and a ``DriveAPI`` (``angular`` for revolute, ``linear`` for
   prismatic).
6. Optional ``CollisionGroup`` prims with self-collision filtering.

Only ``pxr.UsdPhysics`` is used (available from the ``usd-core`` PyPI package);
Omniverse-only ``PhysxSchema`` tuning can be layered on later inside Isaac Sim.

Run::

    python apply_physics_spec.py \\
        --usd ../.intermediate/dishwasher/001/robot.usda \\
        --spec ../.intermediate/dishwasher/001/physics_spec.json \\
        --output ../.intermediate/dishwasher/001/robot_physics.usda
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usd", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_json(path: str) -> dict:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def resolve_prim(stage: Usd.Stage, path: str) -> Usd.Prim:
    """Return the prim at ``path``, falling back to a leaf-name search.

    Guards against small mismatches between the prim path the subagent copied
    from ``scene.json`` and the one Blender actually exported.
    """
    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return prim
    leaf = path.rstrip("/").split("/")[-1]
    for candidate in stage.Traverse():
        if candidate.GetName() == leaf:
            print(f"[WARN] {path} not found; using {candidate.GetPath()}")
            return candidate
    print(f"[WARN] prim not found and unresolved: {path}")
    return prim


def iter_meshes(prim: Usd.Prim):
    for descendant in Usd.PrimRange(prim):
        if descendant.IsA(UsdGeom.Mesh):
            yield descendant


def local_frame(child_world: Gf.Matrix4d, parent_world: Gf.Matrix4d):
    """Pose of ``child_world`` expressed in ``parent_world``'s space.

    Returns ``(translation, rotation_quat)``. Used to set a joint's body0 local
    frame so the joint anchor coincides with the child's current pose and PhysX
    does not yank the bodies together at simulation start.
    """
    rel = child_world * parent_world.GetInverse()
    translation = Gf.Vec3f(rel.ExtractTranslation())
    rotation = Gf.Quatf(rel.GetOrthonormalized().ExtractRotationQuat())
    return translation, rotation


IDENTITY_QUAT = Gf.Quatf(1.0, 0.0, 0.0, 0.0)


def apply_rigid_body(stage: Usd.Stage, rb: dict) -> None:
    prim = resolve_prim(stage, rb["prim_path"])
    if not prim or not prim.IsValid():
        return

    body_api = UsdPhysics.RigidBodyAPI.Apply(prim)
    if rb.get("is_kinematic"):
        body_api.CreateKinematicEnabledAttr().Set(True)

    mass_api = UsdPhysics.MassAPI.Apply(prim)
    mass_api.CreateMassAttr().Set(float(rb["mass_kg"]))
    if "center_of_mass" in rb:
        mass_api.CreateCenterOfMassAttr().Set(Gf.Vec3f(*rb["center_of_mass"]))

    approximation = rb["collision_approximation"]
    mesh_count = 0
    for mesh in iter_meshes(prim):
        UsdPhysics.CollisionAPI.Apply(mesh)
        mesh_collision = UsdPhysics.MeshCollisionAPI.Apply(mesh)
        mesh_collision.CreateApproximationAttr().Set(approximation)
        mesh_count += 1
    if mesh_count == 0:
        print(f"[WARN] no mesh under {rb['prim_path']}; collision not applied")

    bind_physics_material(stage, prim, rb)


def bind_physics_material(stage: Usd.Stage, prim: Usd.Prim, rb: dict) -> None:
    if not any(k in rb for k in ("static_friction", "dynamic_friction", "restitution")):
        return
    mat_path = prim.GetPath().AppendChild("PhysicsMaterial")
    material = UsdShade.Material.Define(stage, mat_path)
    phys_mat = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    phys_mat.CreateStaticFrictionAttr().Set(float(rb.get("static_friction", 0.5)))
    phys_mat.CreateDynamicFrictionAttr().Set(float(rb.get("dynamic_friction", 0.4)))
    phys_mat.CreateRestitutionAttr().Set(float(rb.get("restitution", 0.0)))

    binding = UsdShade.MaterialBindingAPI.Apply(prim)
    binding.Bind(material, UsdShade.Tokens.weakerThanDescendants, "physics")


def apply_articulation_root(stage: Usd.Stage, spec: dict, xf_cache: UsdGeom.XformCache) -> None:
    world_joint_path = spec.get("world_joint_path")
    root_path = spec["articulation_root"]
    if not world_joint_path:
        root_prim = resolve_prim(stage, root_path)
        if root_prim and root_prim.IsValid():
            UsdPhysics.ArticulationRootAPI.Apply(root_prim)
        return

    root_prim = resolve_prim(stage, root_path)
    joint = UsdPhysics.FixedJoint.Define(stage, world_joint_path)
    joint.CreateBody1Rel().SetTargets([root_prim.GetPath()])
    if root_prim and root_prim.IsValid():
        translation, rotation = local_frame(
            xf_cache.GetLocalToWorldTransform(root_prim), Gf.Matrix4d(1.0)
        )
        joint.CreateLocalPos0Attr().Set(translation)
        joint.CreateLocalRot0Attr().Set(rotation)
    joint.CreateLocalPos1Attr().Set(Gf.Vec3f(0.0, 0.0, 0.0))
    joint.CreateLocalRot1Attr().Set(IDENTITY_QUAT)
    UsdPhysics.ArticulationRootAPI.Apply(joint.GetPrim())


def apply_joint(stage: Usd.Stage, jt: dict, xf_cache: UsdGeom.XformCache) -> None:
    joint_type = jt["joint_type"]
    path = jt["prim_path"]
    if joint_type == "revolute":
        joint = UsdPhysics.RevoluteJoint.Define(stage, path)
    elif joint_type == "prismatic":
        joint = UsdPhysics.PrismaticJoint.Define(stage, path)
    else:
        joint = UsdPhysics.FixedJoint.Define(stage, path)

    body0 = resolve_prim(stage, jt["body0"])
    body1 = resolve_prim(stage, jt["body1"])
    joint.CreateBody0Rel().SetTargets([body0.GetPath()])
    joint.CreateBody1Rel().SetTargets([body1.GetPath()])

    if joint_type in ("revolute", "prismatic") and "axis" in jt:
        joint.CreateAxisAttr().Set(jt["axis"])

    if joint_type == "revolute":
        if "lower_limit_deg" in jt:
            joint.CreateLowerLimitAttr().Set(float(jt["lower_limit_deg"]))
        if "upper_limit_deg" in jt:
            joint.CreateUpperLimitAttr().Set(float(jt["upper_limit_deg"]))
    elif joint_type == "prismatic":
        if "lower_limit_m" in jt:
            joint.CreateLowerLimitAttr().Set(float(jt["lower_limit_m"]))
        if "upper_limit_m" in jt:
            joint.CreateUpperLimitAttr().Set(float(jt["upper_limit_m"]))

    if body0 and body0.IsValid() and body1 and body1.IsValid():
        translation, rotation = local_frame(
            xf_cache.GetLocalToWorldTransform(body1),
            xf_cache.GetLocalToWorldTransform(body0),
        )
        joint.CreateLocalPos0Attr().Set(translation)
        joint.CreateLocalRot0Attr().Set(rotation)
        joint.CreateLocalPos1Attr().Set(Gf.Vec3f(0.0, 0.0, 0.0))
        joint.CreateLocalRot1Attr().Set(IDENTITY_QUAT)

    apply_drive(joint, jt)


def apply_drive(joint, jt: dict) -> None:
    joint_type = jt["joint_type"]
    if joint_type == "fixed":
        return
    if not any(k in jt for k in ("drive_stiffness", "drive_damping", "drive_max_force")):
        return
    token = "angular" if joint_type == "revolute" else "linear"
    drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), token)
    drive.CreateStiffnessAttr().Set(float(jt.get("drive_stiffness", 0.0)))
    drive.CreateDampingAttr().Set(float(jt.get("drive_damping", 0.0)))
    if "drive_max_force" in jt:
        drive.CreateMaxForceAttr().Set(float(jt["drive_max_force"]))


def apply_collision_group(stage: Usd.Stage, cg: dict) -> None:
    group = UsdPhysics.CollisionGroup.Define(stage, cg["prim_path"])
    includes = group.GetCollidersCollectionAPI().CreateIncludesRel()
    includes.SetTargets([Sdf.Path(m) for m in cg["members"]])
    if cg.get("filter_self_collision"):
        group.CreateFilteredGroupsRel().SetTargets([Sdf.Path(cg["prim_path"])])


def main() -> None:
    args = parse_args()
    spec = load_json(args.spec)

    stage = Usd.Stage.Open(str(Path(args.usd).expanduser().resolve()))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = stage.GetPrimAtPath("/World")
    if world and world.IsValid():
        stage.SetDefaultPrim(world)

    scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    gravity = spec["physics_scene"]
    scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(*gravity["gravity_direction"]))
    scene.CreateGravityMagnitudeAttr().Set(float(gravity["gravity_magnitude"]))

    xf_cache = UsdGeom.XformCache(Usd.TimeCode.Default())

    for rb in spec["rigid_bodies"]:
        apply_rigid_body(stage, rb)

    apply_articulation_root(stage, spec, xf_cache)

    for jt in spec.get("joints", []):
        apply_joint(stage, jt, xf_cache)

    for cg in spec.get("collision_groups", []):
        apply_collision_group(stage, cg)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage.GetRootLayer().Export(str(output))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
