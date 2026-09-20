import os
import sys
import shutil
import subprocess
import argparse

# Ensure Pillow is installed
def install_pillow():
    try:
        from PIL import Image, ImageOps
        print("Pillow library is already installed.")
    except ImportError:
        print("Pillow not found. Installing Pillow for image resizing...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
            print("Pillow successfully installed.")
        except subprocess.CalledProcessError as e:
            print(f"Error installing Pillow: {e}")
            print("Please run: pip install Pillow")
            sys.exit(1)

def find_sdk_tool(tool_name):
    """Locates SDK tools (makeappx.exe, signtool.exe) in Windows Kits directory."""
    kits_dir = r"C:\Program Files (x86)\Windows Kits"
    if not os.path.exists(kits_dir):
        return None
    
    found_paths = []
    for root, dirs, files in os.walk(kits_dir):
        if tool_name in files:
            # Prefer x64 tools if running on 64-bit Windows
            full_path = os.path.join(root, tool_name)
            if "x64" in root:
                return full_path
            found_paths.append(full_path)
            
    if found_paths:
        return found_paths[0]
    return None

def create_visual_assets(source_image_path, assets_dir):
    """Resizes the source image into all required MSIX logo sizes."""
    from PIL import Image
    
    print(f"Generating visual assets from source: {source_image_path}...")
    os.makedirs(assets_dir, exist_ok=True)
    
    try:
        img = Image.open(source_image_path)
    except Exception as e:
        print(f"Error opening source logo: {e}")
        sys.exit(1)
        
    # Sizes to generate: (Filename, Width, Height, IsSplashOrWide)
    sizes = [
        ("StoreLogo.png", 50, 50, False),
        ("Square150x150Logo.png", 150, 150, False),
        ("Square44x44Logo.png", 44, 44, False),
        ("Wide310x150Logo.png", 310, 150, True),
        ("SplashScreen.png", 620, 300, True)
    ]
    
    bg_color = (31, 31, 46, 255) # Match app theme color (#1f1f2e)
    
    for filename, w, h, is_padded in sizes:
        dest_path = os.path.join(assets_dir, filename)
        if is_padded:
            # Create a background-colored canvas and center a scaled version of the logo
            canvas = Image.new("RGBA", (w, h), bg_color)
            # Scale logo to fit 70% of height of the padded area
            logo_h = int(h * 0.7)
            logo_w = int(img.width * (logo_h / img.height))
            scaled_logo = img.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
            
            # Paste scaled logo in the center
            offset_x = (w - logo_w) // 2
            offset_y = (h - logo_h) // 2
            canvas.paste(scaled_logo, (offset_x, offset_y), scaled_logo if scaled_logo.mode == 'RGBA' else None)
            canvas.save(dest_path, "PNG")
        else:
            # Direct resize/fit
            resized_img = img.resize((w, h), Image.Resampling.LANCZOS)
            resized_img.save(dest_path, "PNG")
            
        print(f"  Created: {filename} ({w}x{h})")

def generate_manifest(manifest_path, identity_name, publisher, publisher_display_name, version, display_name):
    """Generates the AppxManifest.xml file."""
    print("Generating AppxManifest.xml...")
    
    xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">

  <Identity
    Name="{identity_name}"
    Publisher="{publisher}"
    Version="{version}"
    ProcessorArchitecture="x64" />

  <Properties>
    <DisplayName>{display_name}</DisplayName>
    <PublisherDisplayName>{publisher_display_name}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>

  <Dependencies>
    <TargetDeviceFamily Name="Windows.Universal" MinVersion="10.0.17763.0" MaxVersionTested="10.0.22000.0" />
  </Dependencies>

  <Resources>
    <Resource Language="en-us" />
  </Resources>

  <Applications>
    <Application Id="YTDownloaderPro" Executable="YT_Downloader_Pro.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="{display_name}"
        Description="Download YouTube videos and audio extract with ease."
        BackgroundColor="#1f1f2e"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png">
        
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" />
        <uap:SplashScreen Image="Assets\\SplashScreen.png" />
      </uap:VisualElements>
    </Application>
  </Applications>

  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""
    with open(manifest_path, 'w', encoding='utf-8') as f:
        f.write(xml_content.strip())
        
    print("AppxManifest.xml successfully created.")

def build_msix():
    print("="*60)
    print(" YouTube Downloader Pro - MSIX Packaging Assistant")
    print("="*60)
    
    install_pillow()
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="YouTube Downloader Pro MSIX Packager")
    parser.add_argument("--name", default="YTDownloaderProTest", help="Package Name")
    parser.add_argument("--publisher", default="CN=TestPublisher", help="Publisher Distinguished Name")
    parser.add_argument("--publisher-display-name", default="Test Publisher", help="Publisher Display Name")
    parser.add_argument("--version", default="1.0.0.0", help="Package Version")
    parser.add_argument("--display-name", default="YouTube Downloader Pro", help="App Display Name")
    parser.add_argument("--sign", choices=["y", "n"], default="y", help="Sign the package locally")
    parser.add_argument("--non-interactive", action="store_true", help="Run without prompting")
    args = parser.parse_args()

    # Locate SDK tools
    makeappx_path = find_sdk_tool("makeappx.exe")
    signtool_path = find_sdk_tool("signtool.exe")
    
    if not makeappx_path:
        print("ERROR: Windows SDK (makeappx.exe) was not found on your system.")
        print("Please install the Windows 10/11 SDK first.")
        sys.exit(1)
        
    print(f"Found Windows SDK tools:")
    print(f"  MakeAppx: {makeappx_path}")
    if signtool_path:
        print(f"  SignTool: {signtool_path}")
    else:
        print("  SignTool: NOT FOUND (Local signing will be skipped, but packaging is still possible)")

    # Check executable source
    exe_src = os.path.join("dist", "YT_Downloader_Pro.exe")
    if not os.path.exists(exe_src):
        exe_src = os.path.join("static", "dist", "YT_Downloader_Pro.exe")
        
    if not os.path.exists(exe_src):
        print(f"Executable not found at {exe_src}.")
        if args.non_interactive:
            print("Running in non-interactive mode. Building executable first...")
            subprocess.run([sys.executable, "build_exe.py"], check=True)
        else:
            rebuild = input("Would you like to build the executable first using build_exe.py? (y/n) [y]: ").strip().lower()
            if rebuild != 'n':
                print("Running build_exe.py...")
                subprocess.run([sys.executable, "build_exe.py"], check=True)
            else:
                print("Aborting package creation.")
                sys.exit(1)
                
        # Re-check
        exe_src = os.path.join("dist", "YT_Downloader_Pro.exe")
        if not os.path.exists(exe_src):
            exe_src = os.path.join("static", "dist", "YT_Downloader_Pro.exe")
            
        if not os.path.exists(exe_src):
            print("Failed to locate built executable. Aborting.")
            sys.exit(1)
            
    print(f"Using executable: {os.path.abspath(exe_src)}")

    # Prompt user for Microsoft Partner Center Identity info
    identity_name = args.name
    publisher = args.publisher
    publisher_display_name = args.publisher_display_name
    version = args.version
    display_name = args.display_name
    sign_choice = args.sign

    if not args.non_interactive:
        print("\n--- Product Identity Configuration ---")
        print("If you are preparing a submission, enter the values from Microsoft Partner Center.")
        print("If you just want to test locally, press ENTER to use default test values.\n")
        
        identity_name = input(f"Package Name (Identity/Name) [{identity_name}]: ").strip() or identity_name
        publisher = input(f"Publisher ID (Identity/Publisher) [{publisher}]: ").strip() or publisher
        publisher_display_name = input(f"Publisher Display Name [{publisher_display_name}]: ").strip() or publisher_display_name
        version = input(f"App Version [{version}]: ").strip() or version
        display_name = input(f"App Display Name [{display_name}]: ").strip() or display_name
        
    # Ensure Publisher begins with CN=
    if not publisher.startswith("CN="):
        publisher = f"CN={publisher}"

    # Setup directories
    build_dir = "msix_build"
    assets_dir = os.path.join(build_dir, "Assets")
    
    if os.path.exists(build_dir):
        print(f"Cleaning existing build directory: {build_dir}...")
        shutil.rmtree(build_dir)
        
    os.makedirs(build_dir)
    os.makedirs(assets_dir)

    # Copy Executable to build folder
    print(f"Copying executable into packaging directory...")
    shutil.copy2(exe_src, os.path.join(build_dir, "YT_Downloader_Pro.exe"))

    # Generate assets
    source_logo = "store_logo_source.png"
    if not os.path.exists(source_logo):
        print(f"Warning: Source logo '{source_logo}' not found.")
        print("Please copy your high-res logo to this folder as 'store_logo_source.png'")
        sys.exit(1)
        
    create_visual_assets(source_logo, assets_dir)

    # Generate Manifest
    manifest_path = os.path.join(build_dir, "AppxManifest.xml")
    generate_manifest(manifest_path, identity_name, publisher, publisher_display_name, version, display_name)

    # Pack MSIX
    os.makedirs("dist", exist_ok=True)
    msix_output = os.path.join("dist", "YT_Downloader_Pro.msix")
    if os.path.exists(msix_output):
        os.remove(msix_output)
        
    print(f"Packing MSIX to {msix_output}...")
    pack_cmd = [makeappx_path, "pack", "/d", build_dir, "/p", msix_output, "/o"]
    
    try:
        subprocess.run(pack_cmd, check=True)
        print("="*60)
        print("PACKAGING SUCCESSFUL!")
        print(f"Package saved to: {os.path.abspath(msix_output)}")
        print("="*60)
    except subprocess.CalledProcessError as e:
        print(f"MakeAppx execution failed: {e}")
        sys.exit(1)

    # Sign MSIX locally if signtool is present
    if signtool_path:
        if not args.non_interactive:
            print("\nWould you like to sign the package with a local self-signed certificate?")
            print("This allows you to install and test the app on this computer.")
            sign_choice = input("Sign package? (y/n) [y]: ").strip().lower() or "y"
            
        if sign_choice == 'y':
            pfx_path = os.path.join("dist", "YT_Downloader_Pro_Test.pfx")
            cer_path = os.path.join("dist", "YT_Downloader_Pro_Test.cer")
            
            # Clean up old cert files
            if os.path.exists(pfx_path): os.remove(pfx_path)
            if os.path.exists(cer_path): os.remove(cer_path)
            
            print("Creating self-signed certificate...")
            pwd = "password123"
            
            # Use PowerShell to generate the certificate
            ps_script = f"""
            $cert = New-SelfSignedCertificate -Type Custom -Subject "{publisher}" -KeyUsage DigitalSignature -FriendlyName "YT Downloader Pro Dev Cert" -CertStoreLocation "Cert:\\CurrentUser\\My" -NotAfter (Get-Date).AddYears(1) -HashAlgorithm SHA256
            $securePwd = ConvertTo-SecureString -String "{pwd}" -Force -AsPlainText
            Export-PfxCertificate -Cert $cert -FilePath "{pfx_path}" -Password $securePwd
            Export-Certificate -Cert $cert -FilePath "{cer_path}"
            """
            
            ps_cmd = ["powershell", "-Command", ps_script]
            try:
                subprocess.run(ps_cmd, check=True, capture_output=True)
                print("Created self-signed certificate.")
                
                # Sign the MSIX package
                print("Signing the MSIX package...")
                sign_cmd = [
                    signtool_path, "sign", 
                    "/fd", "sha256", 
                    "/a", 
                    "/f", pfx_path, 
                    "/p", pwd, 
                    msix_output
                ]
                
                # Run signtool
                subprocess.run(sign_cmd, check=True, capture_output=True, text=True)
                print("Package signed successfully!")
                print(f"  Test PFX: {os.path.abspath(pfx_path)}")
                print(f"  Test CER: {os.path.abspath(cer_path)}")
                print("\nTo test locally, follow these steps:")
                print("1. Double click the test certificate (.cer) file.")
                print("2. Click 'Install Certificate...' -> select 'Local Machine' -> Next.")
                print("3. Choose 'Place all certificates in the following store' -> Browse -> 'Trusted People' -> OK.")
                print("4. Finish the wizard. Then double-click the .msix file to install and test.")
                
            except subprocess.CalledProcessError as e:
                print(f"Warning: Certificate generation or signing failed: {e.stderr or e.stdout}")
                print("You can still upload the unsigned MSIX package to the Microsoft Store.")
                print("The Store signs all uploaded apps automatically.")

    # Cleanup temporary build dir
    try:
        shutil.rmtree(build_dir)
        print("\nCleaned up temporary build directories.")
    except Exception:
        pass

if __name__ == "__main__":
    build_msix()
