#
# Update requirements.txt to reflect versions installed using the YML file
#
import re
import subprocess

REPO_DIR = "/Users/rjp/repos/OPGEEv4/"

def main():
    reqs_in  = REPO_DIR + "requirements.in"
    reqs_out = REPO_DIR + "requirements.txt"

    with open(reqs_in) as f:
        pkgs = [line.strip() for line in f.readlines() if not line.startswith('#')]

    expr = '^(' + '|'.join(pkgs) + ')'
    cmd = f"conda list | egrep -i '{expr}'"

    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    lines = proc.stdout.split('\n')
    with open(reqs_out, 'w') as f:
        f.write("# This file was generated by the script update-reqs.py. Manual edits may be lost.\n")
        for line in lines:
            if not line:
                continue
            # print(f"Line is '{line}'")
            name, version, _, _ = re.split('\s+', line)
            f.write(f"{name}=={version}\n")

main()