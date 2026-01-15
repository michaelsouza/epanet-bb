import os
import subprocess

np = 128
level = 8
h = 24
sync_interval = 32768
solver = "build/run-epanet3-bb"
for a in [1, 2, 3]:
    cmd = [
        "mpirun",
        "-n",
        str(np),
        solver,
        "-h",
        str(h),
        "-a",
        str(a),
        "-l",
        str(level),
        "-s",
        str(sync_interval),
    ]
    subprocess.run(cmd)
