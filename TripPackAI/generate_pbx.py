#!/usr/bin/env python3
"""Generate minimal TripPackAI.xcodeproj/project.pbxproj (iOS 17, Swift 5)"""
import os, uuid, textwrap, pathlib

root = pathlib.Path(__file__).parent
app = root / "TripPackAI"
files = []
for p in sorted(app.rglob("*.swift")):
    relp = p.relative_to(root)
    files.append((str(p), relp))

def gid():
    return uuid.uuid4().hex.upper()[:24]

# IDs
project_id = gid()
target_app = gid()
target_test = gid()
app_product = gid()
test_product = gid()
pbxproject = gid()
g_main = gid()
g_prods = gid()
g_trip = gid()
bphase_sources_app = gid()
bphase_test = gid()
bphase_fram_app = gid()
bphase_fram_test = gid()
bphase_rsrc = gid()
g_tests = gid()
c_app_debug = gid()
c_app_rel = gid()
c_prj_debug = gid()
c_prj_rel = gid()
c_test_debug = gid()
c_test_rel = gid()
cplist_app = gid()
cplist_test = gid()
bctest = gid()
td_test = gid()

# file refs: path -> (file_ref, build_file) for app; test only file ref
frefs = {}
bfiles = {}
for abspath, relp in files:
    frefs[str(relp)] = gid()
    bfiles[str(relp)] = gid()

testref = (root / "TripPackAITests" / "PackageSolverTests.swift")
test_rel = "TripPackAITests/PackageSolverTests.swift"
test_fref = gid()
test_bfile = gid()

# PBX
lines = [
    f'// !$*UTF8*$!\n',
    f'{{ archiveVersion = 1; classes = {{}}; objectVersion = 56; objects = {{\n',
    f'/* Begin PBXBuildFile section */',
]
for relp, (fr, bld) in [(str(r[1]), (frefs[str(r[1])], bfiles[str(r[1])])) for r in files]:
    lines.append(f"\t\t{bld} /* {os.path.basename(relp)} in Sources */ = {{isa = PBXBuildFile; fileRef = {fr} /* {os.path.basename(relp)} */; }};")
lines.append(f"\t\t{test_bfile} /* PackageSolverTests.swift in Sources */ = {{isa = PBXBuildFile; fileRef = {test_fref} /* PackageSolverTests.swift */; }};")
lines.append('/* End PBXBuildFile section */')

lines.append('/* Begin PBXFileReference section */')
lines.append(f"\t\t{app_product} /* TripPackAI.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = TripPackAI.app; sourceTree = BUILT_PRODUCTS_DIR; }};")
lines.append(f"\t\t{test_product} /* TripPackAITests.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = TripPackAITests.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};")
for abspath, relp in files:
    lines.append(f"\t\t{frefs[str(relp)]} /* {relp} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = \"{relp}\"; sourceTree = \"<group>\"; }};")
lines.append(f"\t\t{test_fref} /* PackageSolverTests.swift */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = PackageSolverTests.swift; sourceTree = \"<group>\"; }};")
lines.append('/* End PBXFileReference section */')

# Groups
ch_trip = "\n".join(f"\t\t\t\t\t{frefs[str(r[1])]} /* {r[1]} */," for r in files)
lines.append('/* Begin PBXGroup section */')
lines.append(f"\t\t{g_main} = {{isa = PBXGroup; children = ( {g_trip} /* TripPackAI */, {g_tests} /* TripPackAITests */, {g_prods} /* Products */, ); sourceTree = \"<group>\"; }};")
lines.append(f"\t\t{g_prods} = {{isa = PBXGroup; children = ( {app_product} /* TripPackAI.app */, {test_product} /* TripPackAITests.xctest */, ); name = Products; sourceTree = \"<group>\"; }};")
lines.append(f"\t\t{g_trip} = {{isa = PBXGroup; children = (")
for abspath, relp in files:
    lines.append(f"\t\t\t\t{frefs[str(relp)]} /* {relp} */,")
lines.append("); path = TripPackAI; sourceTree = \"<group>\"; }};")
lines.append(f"\t\t{g_tests} = {{isa = PBXGroup; children = ( {test_fref} /* PackageSolverTests.swift */ ); path = TripPackAITests; sourceTree = \"<group>\"; }};")
lines.append('/* End PBXGroup section */')

lines.append('/* Begin PBXFrameworksBuildPhase section */')
lines.append(f"\t\t{bphase_fram_app} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = ( ); runOnlyForDeploymentPostprocessing = 0; }};")
lines.append(f"\t\t{bphase_fram_test} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = ( ); runOnlyForDeploymentPostprocessing = 0; }};")
lines.append('/* End PBXFrameworksBuildPhase section */')

lines.append('/* Begin PBXResourcesBuildPhase section */')
lines.append(f"\t\t{bphase_rsrc} = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ( ); runOnlyForDeploymentPostprocessing = 0; }};")
lines.append('/* End PBXResourcesBuildPhase section */')

lines.append('/* Begin PBXNativeTarget section */')
lines.append(f'''\t\t{target_app} /* TripPackAI */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {cplist_app} /* Build configuration list for PBXNativeTarget "TripPackAI" */;
			buildPhases = (
				{bphase_sources_app} /* Sources */,
				{bphase_fram_app} /* Frameworks */,
				{bphase_rsrc} /* Resources */,
			);
			buildRules = (
			);
			dependencies = (
			);
			name = TripPackAI;
			productName = TripPackAI;
			productReference = {app_product} /* TripPackAI.app */;
			productType = "com.apple.product-type.application";
		}};''')
lines.append(f'''\t\t{target_test} /* TripPackAITests */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {cplist_test} /* Build configuration list for PBXNativeTarget "TripPackAITests" */;
			buildPhases = (
				{bphase_test} /* Sources */,
				{bphase_fram_test} /* Frameworks */,
			);
			buildRules = (
			);
			dependencies = (
				{td_test} /* PBXTargetDependency */,
			);
			name = TripPackAITests;
			productName = TripPackAITests;
			productReference = {test_product} /* TripPackAITests.xctest */;
			productType = "com.apple.product-type.bundle.unit-test";
		}};''')
lines.append('/* End PBXNativeTarget section */')

# PBXTargetDependency
lines.append('/* Begin PBXTargetDependency section */')
lines.append(f"\t\t{td_test} /* PBXTargetDependency */ = {{isa = PBXTargetDependency; target = {target_app} /* TripPackAI */; targetProxy = {bctest} /* PBXContainerItemProxy */; }};")
lines.append('/* End PBXTargetDependency section */')
lines.append('/* Begin PBXContainerItemProxy section */')
lines.append(f"\t\t{bctest} /* PBXContainerItemProxy */ = {{isa = PBXContainerItemProxy; containerPortal = {project_id} /* Project object */; proxyType = 1; remoteGlobalIDString = {target_app}; remoteInfo = TripPackAI; }};")
lines.append('/* End PBXContainerItemProxy section */')

# Sources
lines.append('/* Begin PBXSourcesBuildPhase section */')
bld_app = " ".join(bfiles[str(r[1])] for r in files)
lines.append(f"\t\t{bphase_sources_app} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ( " + " ".join(f"\n\t\t\t\t{bfiles[str(r[1])]} /* in Sources */," for r in files) + f"\n\t\t); runOnlyForDeploymentPostprocessing = 0; }};")
# fix 
lines = lines[:-1]
lines.append(f"\t\t{bphase_sources_app} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (")
for r in files:
    lines.append(f"\t\t\t\t{bfiles[str(r[1])]} /* in Sources */,")
lines.append("); runOnlyForDeploymentPostprocessing = 0; };")
lines.append(f"\t\t{bphase_test} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ( {test_bfile} /* in Sources */, ); runOnlyForDeploymentPostprocessing = 0; }};")
lines.append('/* End PBXSourcesBuildPhase section */')

# PBXProject
lines.append('/* Begin PBXProject section */')
lines.append(f"""\t\t{project_id} /* Project object */ = {{
			isa = PBXProject;
			attributes = {{
				BuildIndependentTargetsInParallel = 1;
				LastUpgradeCheck = 1500;
				TargetAttributes = {{
					{target_app} = {{
						CreatedOnToolsVersion = 15.0;
					}};
					{target_test} = {{
						CreatedOnToolsVersion = 15.0;
						TestTargetID = {target_app};
					}};
				}};
			}};
			buildConfigurationList = {pbxproject} /* Build configuration list for PBXProject "TripPackAI" */;
			compatibilityVersion = "Xcode 14.0";
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = ( en, Base, );
			mainGroup = {g_main};
			productRefGroup = {g_prods} /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				{target_app} /* TripPackAI */,
				{target_test} /* TripPackAITests */,
			);
		}};""")
lines.append('/* End PBXProject section */')

# Build configs
def cfg_app(debug):
    return f'''{{ 
			isa = XCBuildConfiguration; 
			buildSettings = {{
				ALWAYS_SEARCH_USER_PATHS = NO; 
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME = AccentColor;
				CODE_SIGN_IDENTITY = "Apple Development";
				CODE_SIGN_STYLE = Automatic; 
				CURRENT_PROJECT_VERSION = 1; 
				DEVELOPMENT_ASSET_PATHS = "";
				DEVELOPMENT_TEAM = "";
				ENABLE_PREVIEWS = YES; 
				GCC_OPTIMIZATION_LEVEL = 0; 
				GENERATE_INFOPLIST_FILE = YES; 
				INFOPLIST_KEY_UILaunchScreen_Generation = YES; 
				INFOPLIST_KEY_UISupportedInterfaceOrientations = UIInterfaceOrientationPortrait;
				IPHONEOS_DEPLOYMENT_TARGET = 17.0; 
				LD_RUNPATH_SEARCH_PATHS = ( "$(inherited)", "@executable_path/Frameworks" );
				MARKETING_VERSION = 1.0; 
				ONLY_ACTIVE_ARCH = {"YES" if debug else "NO"}; 
				PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI; 
				PRODUCT_NAME = "$(TARGET_NAME)"; 
				SDKROOT = iphoneos; 
				SWIFT_VERSION = 5.0; 
				TARGETED_DEVICE_FAMILY = 1; 
			}}; 
			name = {("Debug" if debug else "Release")};
		}};'''

# simplify - the script has bug in replacement. Just write a static pbx

print("Wrote pbx to stdout - use hand-crafted file instead", file=__import__("sys").stderr)

ENDPY
echo "falling back to hand project"
