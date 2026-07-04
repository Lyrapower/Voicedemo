#!/usr/bin/env python3
import uuid, pathlib

root = pathlib.Path(__file__).resolve().parents[1]
pkg_dir = root / "TripPackAI"
swift = sorted(
    p.relative_to(root) for p in pkg_dir.rglob("*.swift") if p.suffix == ".swift"
)


def in_package_path(rel: pathlib.Path) -> str:
    """Path inside TripPackAI/ for PBX file refs (group already has path = TripPackAI)."""
    p = rel
    if p.parts and p.parts[0] == "TripPackAI":
        return str(pathlib.Path(*p.parts[1:]))
    return str(p)

def hid():
    return uuid.uuid4().hex[:24].upper()

# IDs
P = hid()
Gmain, Gprod, Gtrip = hid(), hid(), hid()
Papp, Tapp = hid(), hid()
Bsrc, Bfram, Bres = hid(), hid(), hid()
Aref, Basset = hid(), hid()
CprojD, CprojR = hid(), hid()
CappD, CappR = hid(), hid()
CLp, CLapp = hid(), hid()

fr_bf = {str(s): (hid(), hid()) for s in swift}

o = []
def W(x): o.append(x)
W("// !$*UTF8*$!\n{")
W("\tarchiveVersion = 1;\n\tclasses = {};\n\tobjectVersion = 56;\n\tobjects = {")
W("/* Begin PBXBuildFile section */")
for s in sorted(swift, key=str):
    bfile, fref = fr_bf[str(s)]
    rel_in_pkg = in_package_path(s)
    W(f"\t\t{bfile} /* in Sources */ = {{isa = PBXBuildFile; fileRef = {fref} /* {rel_in_pkg} */; }};")
W(f"\t\t{Basset} /* in Resources */ = {{isa = PBXBuildFile; fileRef = {Aref} /* Assets.xcassets */; }};")
W("/* End PBXBuildFile section */")
W("/* Begin PBXFileReference section */")
W(f"\t\t{Papp} = {{isa = PBXFileReference; explicitFileType = wrapper.application; path = TripPackAI.app; sourceTree = BUILT_PRODUCTS_DIR; }};")
for s in sorted(swift, key=str):
    _b, fref = fr_bf[str(s)]
    rel_in_pkg = in_package_path(s)
    W(f"\t\t{fref} = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = \"{rel_in_pkg}\"; sourceTree = \"<group>\"; }};")
W(f"\t\t{Aref} = {{isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = Assets.xcassets; sourceTree = \"<group>\"; }};")
W("/* End PBXFileReference section */")
W("/* Begin PBXFrameworksBuildPhase section */")
W(f"\t\t{Bfram} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = ( ); runOnlyForDeploymentPostprocessing = 0; }};")
W("/* End PBXFrameworksBuildPhase section */")
W("/* Begin PBXGroup section */")
W(f"\t\t{Gmain} = {{isa = PBXGroup; children = ( {Gtrip} /* src */, {Gprod} /* Products */ ); sourceTree = \"<group>\"; }};")
W(f"\t\t{Gprod} = {{isa = PBXGroup; children = ( {Papp} ); name = Products; sourceTree = \"<group>\"; }};")
W(f"\t\t{Gtrip} = {{isa = PBXGroup; children = (")
for s in sorted(swift, key=str):
    _b, fref = fr_bf[str(s)]
    rel_in_pkg = in_package_path(s)
    W(f"\t\t\t{fref} /* {rel_in_pkg} */,")
W(f"\t\t\t{Aref} /* Assets */,")
W(f"\t\t); path = TripPackAI; sourceTree = \"<group>\"; }};")
W("/* End PBXGroup section */")
W("/* Begin PBXResourcesBuildPhase section */")
W(f"\t\t{Bres} = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ( {Basset}, ); runOnlyForDeploymentPostprocessing = 0; }};")
W("/* End PBXResourcesBuildPhase section */")
W("/* Begin PBXNativeTarget section */")
W(f"\t\t{Tapp} = {{isa = PBXNativeTarget; buildConfigurationList = {CLapp}; buildPhases = ( {Bsrc}, {Bfram}, {Bres} ); name = TripPackAI; productName = TripPackAI; productReference = {Papp}; productType = com.apple.product-type.application; }};")
W("/* End PBXNativeTarget section */")
W("/* Begin PBXSourcesBuildPhase section */")
W(f"\t\t{Bsrc} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (")
for s in sorted(swift, key=str):
    bfile, fref = fr_bf[str(s)]
    W(f"\t\t\t{bfile},")
W(f"\t\t); runOnlyForDeploymentPostprocessing = 0; }};")
W("/* End PBXSourcesBuildPhase section */")
W("/* Begin PBXProject section */")
W(f"\t\t{P} = {{isa = PBXProject; attributes = {{BuildIndependentTargetsInParallel = 1;}}; buildConfigurationList = {CLp}; compatibilityVersion = \"Xcode 14.0\"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en,Base,); mainGroup = {Gmain}; targets = ( {Tapp} /* TripPackAI */ );}};")
W("/* End PBXProject section */")
W("/* Begin XCBuildConfiguration section */")
W(f"\t\t{CprojD} = {{isa = XCBuildConfiguration; buildSettings = {{ CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 5.0; }}; name = Debug; }};")
W(f"\t\t{CprojR} = {{isa = XCBuildConfiguration; buildSettings = {{ CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 5.0; }}; name = Release; }};")
W(f"\t\t{CappD} = {{isa = XCBuildConfiguration; buildSettings = {{ ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; CLANG_TREAT_WARNINGS_AS_ERRORS = NO; CODE_SIGN_STYLE = Automatic; CODE_SIGNING_ALLOWED = YES; \"CODE_SIGN_IDENTITY[sdk=iphonesimulator*]\" = \"-\"; DEVELOPMENT_ASSET_PATHS = \"\"; ENABLE_PREVIEWS = NO; ENABLE_TESTABILITY = YES; GCC_OPTIMIZATION_LEVEL = 0; GENERATE_INFOPLIST_FILE = YES; INFOPLIST_FILE = TripPackAI/Info.plist; INFOPLIST_KEY_CFBundleDisplayName = \"TripPack AI\"; INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES; INFOPLIST_KEY_UILaunchScreen_Generation = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"$(inherited)\", \"@executable_path/Frameworks\"); LOCALIZATION_PREFERS_STRING_CATALOGS = NO; MARKETING_VERSION = 1.0; ONLY_ACTIVE_ARCH = YES; PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI; PRODUCT_NAME = \"$(TARGET_NAME)\"; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_TREAT_WARNINGS_AS_ERRORS = NO; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; }}; name = Debug; }};")
W(f"\t\t{CappR} = {{isa = XCBuildConfiguration; buildSettings = {{ ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; CLANG_TREAT_WARNINGS_AS_ERRORS = NO; CODE_SIGN_STYLE = Automatic; DEVELOPMENT_ASSET_PATHS = \"\"; ENABLE_PREVIEWS = NO; GENERATE_INFOPLIST_FILE = YES; INFOPLIST_FILE = TripPackAI/Info.plist; INFOPLIST_KEY_CFBundleDisplayName = \"TripPack AI\"; INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES; INFOPLIST_KEY_UILaunchScreen_Generation = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"$(inherited)\", \"@executable_path/Frameworks\"); LOCALIZATION_PREFERS_STRING_CATALOGS = NO; MARKETING_VERSION = 1.0; PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI; PRODUCT_NAME = \"$(TARGET_NAME)\"; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_TREAT_WARNINGS_AS_ERRORS = NO; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; }}; name = Release; }};")
W("/* End XCBuildConfiguration section */")
W("/* Begin XCConfigurationList section */")
W(f"\t\t{CLp} = {{isa = XCConfigurationList; buildConfigurations = ( {CprojD}, {CprojR} ); defaultConfigurationName = Release; }};")
W(f"\t\t{CLapp} = {{isa = XCConfigurationList; buildConfigurations = ( {CappD}, {CappR} ); defaultConfigurationName = Debug; }};")
W("/* End XCConfigurationList section */")
W("\t};\n\trootObject = " + P + " /* Project */;\n}\n")
text = "\n".join(o)
out = root / "TripPackAI.xcodeproj" / "project.pbxproj"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(text)
print("Wrote", out, "lines", len(o))

scheme_dir = root / "TripPackAI.xcodeproj" / "xcshareddata" / "xcschemes"
scheme_dir.mkdir(parents=True, exist_ok=True)
scheme_path = scheme_dir / "TripPackAI.xcscheme"
scheme_path.write_text(
    f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1500" version="1.7">
  <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
    <BuildActionEntries>
      <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
        <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{Tapp}" BuildableName="TripPackAI.app" BlueprintName="TripPackAI" ReferencedContainer="container:TripPackAI.xcodeproj">
        </BuildableReference>
      </BuildActionEntry>
    </BuildActionEntries>
  </BuildAction>
  <TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES" shouldAutocreateTestPlan="YES"/>
  <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES">
    <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{Tapp}" BuildableName="TripPackAI.app" BlueprintName="TripPackAI" ReferencedContainer="container:TripPackAI.xcodeproj">
    </BuildableReference>
  </LaunchAction>
  <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES">
    <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{Tapp}" BuildableName="TripPackAI.app" BlueprintName="TripPackAI" ReferencedContainer="container:TripPackAI.xcodeproj">
    </BuildableReference>
  </ProfileAction>
  <AnalyzeAction buildConfiguration="Debug"/>
  <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
"""
)
print("Wrote", scheme_path)
