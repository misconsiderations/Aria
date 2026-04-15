#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import json
import base64
import zlib
import hashlib
import random
import shutil
from logger import setup_file_logger

setup_file_logger()

class _SYS:
    def __init__(self):
        self._K = b'wisd0m_m1n1_2024'
        self._CHK = self._INIT()
    
    def _INIT(self):
        d = b'system_validator'
        return hashlib.sha256(d).hexdigest()[:16]
    
    def _O(self, d):
        k = self._K
        kb = k * (len(d)//len(k)+1)
        return bytes(a^b for a,b in zip(d,kb))
    
    def _P(self, m):
        return base64.b64decode(m)

def cls():
    os.system('cls' if os.name=='nt' else 'clear')

def col(t,c):
    cc = {'r':'\033[91m','g':'\033[92m','y':'\033[93m','b':'\033[94m','m':'\033[95m','c':'\033[96m','0':'\033[0m'}
    return cc.get(c,cc['c'])+t+cc['0']


def head():
    banner = [
        "___      ____   ___    _",
        "/   |    / __ \\ /   |  (_)",
        "/ /| |   / /_/ // /| | / /",
        "/ ___ |  / _, _// ___ |/ /",
        "/_/  |_| /_/ |_|/_/  |_/_/",
        "",
        "Aria - Premium Discord Automation"
    ]
    width = shutil.get_terminal_size((80, 20)).columns
    centered = "\n".join(line.center(width) for line in banner)
    print(col(centered, 'c'))

def check_py():
    print(col("\n[+] Python check:",'b'))
    if sys.version_info < (3,8):
        print(col("  ✗ Python 3.8+ required",'r'))
        return False
    print(col(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}",'g'))
    return True

def inst_all():
    pkgs = [
        "curl-cffi>=0.6.0",
        "websocket-client>=1.6.0",
        "websockets>=11.0.0",
        "aiohttp>=3.9.0",
        "flask>=2.3.0",
        "colorama>=0.4.6",
        "discord.py>=2.3.0"
    ]
    print(col("\n[+] Installing packages:",'b'))
    for p in pkgs:
        print(col(f"  {p}",'y'),end='')
        try:
            subprocess.check_call([sys.executable,"-m","pip","install","-q",p.split('>=')[0]], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(col(" ✓",'g'))
        except:
            try:
                subprocess.check_call([sys.executable,"-m","pip","install",p.split('>=')[0]])
                print(col(" ✓",'g'))
            except:
                print(col(" ✗",'r'))
    return True

def chk_all():
    required = [
        "main.py", "bot.py", "api_client.py", "header_spoofer.py", 
        "rate_limit.py", "cache.py", "config.py", "owner.py",
        "nitro.py", "afk_system.py", "anti_gc_trap.py",
        "backup.py", "moderation.py", "voice.py", "webpanel.py",
        "error_handler.py", "data_engine.py", "analytics.py",
        "notification.py", "host.py", "boost_manager.py",
        "boost_commands.py"
    ]
    
    optional = [
        "requirements.txt", "runner.py", "aria.py", "agc_whitelist.json",
        "afk_state.json", "boost_state.json", "analytics.json",
        "aria_data.json", "errors.json", "alerts.json"
    ]
    
    print(col("\n[+] Core files:",'b'))
    missing_req = []
    for f in required:
        if os.path.exists(f):
            print(col(f"  ✓ {f}",'g'))
        else:
            print(col(f"  ✗ {f}",'r'))
            missing_req.append(f)
    
    print(col("\n[+] Optional files:",'b'))
    for f in optional:
        if os.path.exists(f):
            print(col(f"  • {f}",'c'))
        else:
            print(col(f"  ○ {f}",'y'))
    
    if missing_req:
        print(col(f"\n✗ Missing {len(missing_req)} required files:",'r'))
        for f in missing_req[:5]:
            print(col(f"  - {f}",'r'))
        if len(missing_req) > 5:
            print(col(f"  ... and {len(missing_req)-5} more",'r'))
        return False
    return True

def mk_cfg():
    print(col("\n[+] Configuration:",'b'))
    if os.path.exists("config.json"):
        print(col("  ✓ config.json exists",'g'))
        return True
    
    print(col("\nEnter selfbot token:",'y'))
    t = input("  ").strip()
    if not t:
        print(col("  ✗ Token required",'r'))
        return False

    print(col("\nEnter bot token for the Discord gateway client (optional, press Enter to skip):",'y'))
    sbt = input("  ").strip()
    
    cfg = {
        "token": t,
        "prefix": ";",
        "auto_restart": True,
        "logging": True,
        "rate_limit_delay": 0.1,
        "cache_enabled": True,
        "max_message_cache": 1000,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "impersonate_browser": "chrome120",
        "discord_bot_token": sbt,
    }
    
    try:
        with open("config.json","w") as f:
            json.dump(cfg,f,indent=4)
        print(col("  ✓ Config saved",'g'))
        return True
    except:
        print(col("  ✗ Save failed",'r'))
        return False

def run_bot():
    print(col("\n[+] Starting bot...",'b'))
    if not os.path.exists("config.json"):
        print(col("  ✗ No config file",'r'))
        return
    
    try:
        subprocess.run([sys.executable,"main.py"])
    except KeyboardInterrupt:
        print(col("\n[!] Stopped",'y'))
    except Exception as e:
        print(col(f"\n[!] Error: {e}",'r'))

def check_data():
    print(col("\n[+] Data files:",'b'))
    data_files = ["afk_state.json","boost_state.json","agc_whitelist.json"]
    for f in data_files:
        if os.path.exists(f):
            print(col(f"  • {f}",'c'))
        else:
            print(col(f"  ○ {f} (will be created)",'y'))

def show_info():
    print(col("\n[+] System info:",'b'))
    print(col(f"  OS: {os.name}",'c'))
    print(col(f"  Dir: {os.getcwd()}",'c'))
    print(col(f"  Files: {len([f for f in os.listdir('.') if f.endswith('.py')])} Python files",'c'))

def menu():
    cls()
    head()
    opts = [
        "1. Full system setup",
        "2. Check all files",
        "3. Install packages",
        "4. Create config",
        "5. Run main bot",
        "6. System info",
        "7. Exit"
    ]
    for o in opts:
        print(col(f"  {o}",'w'))
    print()
    return input(col("Select: ",'y')).strip()

def main():
    # Change to script directory to ensure relative paths work correctly
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    sys_check = _SYS()
    
    while True:
        c = menu()
        
        if c == "1":
            if check_py() and chk_all() and inst_all() and mk_cfg():
                print(col("\n✓ Setup complete",'g'))
                input(col("\nPress Enter to run bot...",'y'))
                run_bot()
            else:
                print(col("\n✗ Setup failed",'r'))
        
        elif c == "2":
            chk_all()
            check_data()
        
        elif c == "3":
            inst_all()
        
        elif c == "4":
            mk_cfg()
        
        elif c == "5":
            run_bot()
        
        elif c == "6":
            show_info()

        elif c == "7":
            print(col("\nExiting...",'c'))
            break
        
        else:
            print(col("\nInvalid option",'r'))
        
        input(col("\nPress Enter...",'y'))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(col("\n\nInterrupted",'r'))
        sys.exit(0)
    except Exception as e:
        print(col(f"\nError: {e}",'r'))
        sys.exit(1)