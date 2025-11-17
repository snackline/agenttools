#!/usr/bin/env python3

import subprocess

repos = ["Repos here"]

for repo in repos:
    print(f"Making mirror repo for {repo}")
    out_make = subprocess.run(
        ["./make_repo.sh", repo],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True
    )
    print(f"Success making mirror repo for {repo}")