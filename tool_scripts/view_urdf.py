"""view_urdf.py — Load a generated model.urdf in PyBullet with joint sliders.

Local validation helper (not part of the automated loop). It opens a URDF in the
PyBullet GUI and adds a slider for every revolute/prismatic joint so you can
exercise the articulation. Mesh paths in the URDF are relative to the URDF file,
so the viewer chdirs into that directory.

Run::

    python tool_scripts/view_urdf.py \\
        --urdf .intermediate/dishwasher/001/iterations/006/model.urdf

Requires ``pybullet`` (``pip install pybullet``).
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pybullet as p


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urdf", required=True, help="Path to model.urdf.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    urdf = Path(args.urdf).expanduser().resolve()
    if not urdf.is_file():
        raise FileNotFoundError(urdf)

    os.chdir(urdf.parent)
    p.connect(p.GUI)
    p.resetDebugVisualizerCamera(1.2, 60, -25, [0.0, -0.15, 0.25])
    p.setGravity(0, 0, 0)

    robot = p.loadURDF(urdf.name, useFixedBase=True)
    joints = []
    for i in range(p.getNumJoints(robot)):
        info = p.getJointInfo(robot, i)
        if info[2] in (p.JOINT_REVOLUTE, p.JOINT_PRISMATIC):
            joints.append((i, info[1].decode(), float(info[8]), float(info[9])))

    sliders = [p.addUserDebugParameter(n, lo, hi, lo) for _, n, lo, hi in joints]

    print(f"Loaded {urdf.name} — use the sliders in the PyBullet window.")
    while p.isConnected():
        for slider, (jid, _, _, _) in zip(sliders, joints):
            try:
                p.resetJointState(robot, jid, p.readUserDebugParameter(slider))
            except p.error:
                return
        p.stepSimulation()
        time.sleep(1.0 / 60.0)


if __name__ == "__main__":
    main()
