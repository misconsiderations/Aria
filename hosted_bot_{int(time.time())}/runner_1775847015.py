
import sys, os, json, time, subprocess, shutil

temp_dir = "hosted_bot_{int(time.time())}"
os.makedirs(temp_dir, exist_ok=True)

for file in os.listdir("."):
    if file.endswith(".py"):
        shutil.copy(file, os.path.join(temp_dir, file))

os.chdir(temp_dir)

main_py_content = ""
with open("main.py", "r") as f:
    main_py_content = f.read()

lines = main_py_content.split('\n')
new_lines = []

i = 0
while i < len(lines):
    line = lines[i]
    
    if line.strip().startswith('@bot.command(name="host"'):
        i += 2
        continue
    
    if line.strip().startswith('@bot.command(name="stophost"'):
        i += 2
        continue
    
    if line.strip().startswith('@bot.command(name="listhosted"'):
        i += 2
        continue
    
    new_lines.append(line)
    i += 1

with open("main.py", "w") as f:
    f.write('\n'.join(new_lines))

with open("config.json", "w") as f:
    json.dump({"token": "MzUxNzE5ODEyMjI3MTM3NTM3.GgYicN.KVXNGumTaBGrUG3IGafKjnNw-HYFO7dNcZRTsw", "prefix": ";"}, f)

subprocess.run([sys.executable, "main.py"])
