import os
import sys
import subprocess

def find_iscc():
    paths = [
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Inno Setup 6', 'ISCC.exe'),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe"
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def build_installer():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    exe_path = os.path.join('dist', 'YT_Downloader_Pro.exe')
    if not os.path.exists(exe_path):
        print("Compiled executable not found in dist/. Building executable first...")
        subprocess.run([sys.executable, 'build_exe.py'], check=True)

    iscc_exe = find_iscc()
    if not iscc_exe:
        print("Inno Setup compiler (ISCC.exe) not found.")
        print("Please install Inno Setup via: winget install JRSoftware.InnoSetup")
        sys.exit(1)

    print(f"Found Inno Setup compiler: {iscc_exe}")
    print("Compiling installer from installer.iss...")
    
    cmd = [iscc_exe, 'installer.iss']
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"Installer compilation failed with exit code {res.returncode}")
        sys.exit(res.returncode)

    setup_exe = os.path.join('dist', 'YT_Downloader_Pro_Setup.exe')
    if os.path.exists(setup_exe):
        print("\n" + "="*60)
        print("INSTALLER BUILD SUCCESSFUL!")
        print(f"Setup Installer: {os.path.abspath(setup_exe)}")
        print("="*60)
        print("You can run this setup file to install YouTube Downloader Pro,")
        print("which places the application shortcut on your Desktop and Start Menu.")
    else:
        print("Error: Could not locate compiled installer in dist/ folder.")

if __name__ == '__main__':
    build_installer()
