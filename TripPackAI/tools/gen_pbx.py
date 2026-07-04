#!/usr/bin/env python3
import pathlib, os, textwrap, subprocess

root = pathlib.Path(__file__).resolve().parents[1]
app_src = root / "TripPackAI"
swift = sorted(p.relative_to(root) for p in app_src.rglob("*.swift") if p.is_file())
test_file = root / "TripPackAITests" / "PackageSolverTests.swift"

g = lambda: __import__("uuid").uuid4().hex[:24].upper()
ids = {k: g() for k in [
    "project", "g_main", "g_prod", "g_trip", "g_tests", "p_app", "p_test", "t_app", "t_test",
    "b_sources_app", "b_sources_test", "b_f_app", "b_f_test", "b_res", "cplist_p", "c_app_d", "c_app_r", "c_p_d", "c_p_r",
    "c_test_d", "c_test_r", "c_t_app", "c_t_test", "t_test_dep", "proxy", "pbxp"
]}

# file refs
fr = {str(s): (g(), g()) for s in swift}  # (fileref, buildfile)
t_fr, t_b = g(), g()

def sec(lines):
    return "\n".join(lines) + "\n"

def fref(path: pathlib.Path, fid, typ="sourcecode.swift"):
    return f'\t\t{fid} /* {path.name} */ = {{isa = PBXFileReference; lastKnownFileType = {typ}; path = "{path.as_posix()}"; sourceTree = "<group>"; }};'

# groups children
children_trip = "\n".join(f"\t\t\t\t{fr[str(p)][0]} /* {p} */," for p in sorted(swift, key=str))

pbx = []
pbx.append('// !$*UTF8*$!\n{')
pbx.append('    archiveVersion = 1;')
pbx.append('    classes = {};')
pbx.append('    objectVersion = 56;')
pbx.append('    objects = {')
pbx.append('/* Begin PBXBuildFile section */')
for p in sorted(swift, key=str):
    bid, relid = fr[str(p)]
    pbx.append(f"\t\t{bid} /* {p} in Sources */ = {{isa = PBXBuildFile; fileRef = {relid} /* {p} */; }};")
pbx.append(f"\t\t{t_b} /* PackageSolverTests.swift in Sources */ = {{isa = PBXBuildFile; fileRef = {t_fr} /* PackageSolverTests.swift */; }};")
pbx.append('/* End PBXBuildFile section */')
pbx.append('/* Begin PBXFileReference section */')
pbx.append(f"\t\t{ids['p_app']} /* TripPackAI.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = TripPackAI.app; sourceTree = BUILT_PRODUCTS_DIR; }};")
pbx.append(f"\t\t{ids['p_test']} /* TripPackAITests.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = TripPackAITests.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};")
for p in sorted(swift, key=str):
    pbx.append(fref(root / p, fr[str(p)][0]))
pbx.append(f"\t\t{t_fr} /* PackageSolverTests.swift */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = PackageSolverTests.swift; sourceTree = \"<group>\"; }};")
pbx.append('/* End PBXFileReference section */')
pbx.append('/* Begin PBXFrameworksBuildPhase section */')
pbx.append(f"\t\t{ids['b_f_app']} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};")
pbx.append(f"\t\t{ids['b_f_test']} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};")
pbx.append('/* End PBXFrameworksBuildPhase section */')
pbx.append('/* Begin PBXGroup section */')
pbx.append(f"\t\t{ids['g_main']} = {{isa = PBXGroup; children = ( {ids['g_trip']}, {ids['g_tests']}, {ids['g_prod']}, ); sourceTree = \"<group>\"; }};")
pbx.append(f"\t\t{ids['g_prod']} = {{isa = PBXGroup; children = ( {ids['p_app']}, {ids['p_test']}, ); name = Products; sourceTree = \"<group>\"; }};")
pbx.append(f"\t\t{ids['g_trip']} = {{isa = PBXGroup; children = (")
for p in sorted(swift, key=str):
    pbx.append(f"\t\t\t\t{fr[str(p)][0]} /* {p} */,")
pbx.append("\t\t\t); path = TripPackAI; sourceTree = \"<group>\"; };")
pbx.append(f"\t\t{ids['g_tests']} = {{isa = PBXGroup; children = ( {t_fr} /* PackageSolverTests.swift */ ); path = TripPackAITests; sourceTree = \"<group>\"; }};")
pbx.append('/* End PBXGroup section */')
pbx.append('/* Begin PBXResourcesBuildPhase section */')
pbx.append(f"\t\t{ids['b_res']} = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }};")
pbx.append('/* End PBXResourcesBuildPhase section */')
pbx.append('/* Begin PBXContainerItemProxy section */')
pbx.append(f"\t\t{ids['proxy']} = {{isa = PBXContainerItemProxy; containerPortal = {ids['project']}; proxyType = 1; remoteGlobalIDString = {ids['t_app']}; remoteInfo = TripPackAI; }};")
pbx.append('/* End PBXContainerItemProxy section */')
pbx.append('/* Begin PBXTargetDependency section */')
pbx.append(f"\t\t{ids['t_test_dep']} = {{isa = PBXTargetDependency; target = {ids['t_app']} /* TripPackAI */; targetProxy = {ids['proxy']}; }};")
pbx.append('/* End PBXTargetDependency section */')
pbx.append('/* Begin PBXNativeTarget section */')
pbx.append(f"\t\t{ids['t_app']} = {{isa = PBXNativeTarget; buildConfigurationList = {ids['c_t_app']}; buildPhases = ( {ids['b_sources_app']}, {ids['b_f_app']}, {ids['b_res']}, ); buildRules = (); dependencies = (); name = TripPackAI; productName = TripPackAI; productReference = {ids['p_app']}; productType = com.apple.product-type.application; }};")
pbx.append(f"\t\t{ids['t_test']} = {{isa = PBXNativeTarget; buildConfigurationList = {ids['c_t_test']}; buildPhases = ( {ids['b_sources_test']}, {ids['b_f_test']}, ); buildRules = (); dependencies = ( {ids['t_test_dep']}, ); name = TripPackAITests; productName = TripPackAITests; productReference = {ids['p_test']}; productType = com.apple.product-type.bundle.unit-test; }};")
pbx.append('/* End PBXNativeTarget section */')
pbx.append('/* Begin PBXSourcesBuildPhase section */')
bapp = " ".join(f"\t\t\t\t{fr[str(p)][1]}," for p in sorted(swift, key=str))
# fix the join - we need newlines
pbx.append(f"\t\t{ids['b_sources_app']} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (")
for p in sorted(swift, key=str):
    pbx.append(f"\t\t\t\t{fr[str(p)][1]},")
pbx.append("\t\t); runOnlyForDeploymentPostprocessing = 0; };")
pbx.append(f"\t\t{ids['b_sources_test']} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ( {t_b}, ); runOnlyForDeploymentPostprocessing = 0; }};")
pbx.append('/* End PBXSourcesBuildPhase section */')
pbx.append('/* Begin PBXProject section */')
pbx.append(f"""\t\t{ids['project']} = {{isa = PBXProject; attributes = {{BuildIndependentTargetsInParallel = 1; LastUpgradeCheck = 1500; TargetAttributes = {{"{ids['t_test']}" = {{TestTargetID = {ids['t_app']}; }}; }}; }}; buildConfigurationList = {ids['cplist_p']}; compatibilityVersion = "Xcode 14.0"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en,Base,); mainGroup = {ids['g_main']}; productRefGroup = {ids['g_prod']}; projectDirPath = ""; projectRoot = ""; targets = ( {ids['t_app']}, {ids['t_test']}, ); }};""")
pbx.append('/* End PBXProject section */')
# XCBuild
pbx.append('/* Begin XCBuildConfiguration section */')
pbx.append(f"\t\t{ids['c_p_d']} = {{isa = XCBuildConfiguration; buildSettings = {{ALWAYS_SEARCH_USER_PATHS = NO; CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 5.0; }}; name = Debug; }};")
pbx.append(f"\t\t{ids['c_p_r']} = {{isa = XCBuildConfiguration; buildSettings = {{ALWAYS_SEARCH_USER_PATHS = NO; CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 5.0; }}; name = Release; }};")
app_dbg = f"""
		{ids['c_app_d']} = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				CODE_SIGN_IDENTITY = "Apple Development";
				"CODE_SIGN_IDENTITY[sdk=iphonesimulator*]" = "-";
				CODE_SIGN_STYLE = Automatic;
				CURRENT_PROJECT_VERSION = 1;
				DEVELOPMENT_TEAM = "";
				ENABLE_TESTABILITY = YES;
				ENABLE_PREVIEWS = YES;
				GENERATE_INFOPLIST_FILE = YES;
				INFOPLIST_KEY_UILaunchScreen_Generation = YES;
				INFOPLIS_KEY_UISupportedInterfaceOrientations = UIInterfaceOrientationPortrait;
				INFOPLIST_KEY_UISupportedInterfaceOrientations = UIInterfaceOrientationPortrait;
				IPHONEOS_DEPLOYMENT_TARGET = 17.0;
				LD_RUNPATH_SEARCH_PATHS = ( "$(inherited)", "@executable_path/Frameworks" );
				MARKETING_VERSION = 1.0;
				ONLY_ACTIVE_ARCH = YES;
				PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI;
				PRODUCT_NAME = "$(TARGET_NAME)";
				SDKROOT = iphoneos;
				SUPPORTED_PLATFORMS = "iphoneos iphonesimulator";
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = 1;
			}};
			name = Debug;
		}};""".replace("\n\t\t", "\n\t\t")
pbx.append(f"\t\t{ids['c_app_d']} = {{isa = XCBuildConfiguration; buildSettings = {{ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; CODE_SIGN_IDENTITY = \"-\"; \"CODE_SIGN_IDENTITY[sdk=iphonesimulator*]\" = \"-\"; CODE_SIGNING_REQUIRED = NO; CODE_SIGNING_ALLOWED = YES; DEVELOPMENT_ASSET_PATHS = \"\"; ENABLE_PREVIEWS = YES; ENABLE_TESTABILITY = YES; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"$(inherited)\", \"@executable_path/Frameworks\"); MARKETING_VERSION = 1.0; ONLY_ACTIVE_ARCH = YES; PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI; PRODUCT_NAME = \"$(TARGET_NAME)\"; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; }}; name = Debug; }};")
pbx.append(f"\t\t{ids['c_app_r']} = {{isa = XCBuildConfiguration; buildSettings = {{ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; DEVELOPMENT_ASSET_PATHS = \"\"; ENABLE_PREVIEWS = YES; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"$(inherited)\", \"@executable_path/Frameworks\"); MARKETING_VERSION = 1.0; PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI; PRODUCT_NAME = \"$(TARGET_NAME)\"; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; }}; name = Release; }};")
pbx.append(f"\t\t{ids['c_test_d']} = {{isa = XCBuildConfiguration; buildSettings = {{BUNDLE_LOADER = \"$(TEST_HOST)\"; CODE_SIGNING_ALLOWED = NO; CODE_SIGNING_REQUIRED = NO; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"$(inherited)\", \"@executable_path/Frameworks\", \"@loader_path/Frameworks\"); MARKETING_VERSION = 1.0; PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAITests; PRODUCT_NAME = \"$(TARGET_NAME)\"; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; TEST_HOST = \"$(BUILT_PRODUCTS_DIR)/TripPackAI.app/TripPackAI\"; }}; name = Debug; }};")
pbx.append(f"\t\t{ids['c_test_r']} = {{isa = XCBuildConfiguration; buildSettings = {{BUNDLE_LOADER = \"$(TEST_HOST)\"; CODE_SIGNING_ALLOWED = NO; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"$(inherited)\", \"@executable_path/Frameworks\", \"@loader_path/Frameworks\"); MARKETING_VERSION = 1.0; PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAITests; PRODUCT_NAME = \"$(TARGET_NAME)\"; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; TEST_HOST = \"$(BUILT_PRODUCTS_DIR)/TripPackAI.app/TripPackAI\"; }}; name = Release; }};")
pbx.append('/* End XCBuildConfiguration section */')
pbx.append('/* Begin XCConfigurationList section */')
pbx.append(f"\t\t{ids['cplist_p']} = {{isa = XCConfigurationList; buildConfigurations = ( {ids['c_p_d']}, {ids['c_p_r']}, ); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; }};")
pbx.append(f"\t\t{ids['c_t_app']} = {{isa = XCConfigurationList; buildConfigurations = ( {ids['c_app_d']}, {ids['c_app_r']}, ); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; }};")
pbx.append(f"\t\t{ids['c_t_test']} = {{isa = XCConfigurationList; buildConfigurations = ( {ids['c_test_d']}, {ids['c_test_r']}, ); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; }};")
pbx.append('/* End XCConfigurationList section */')
pbx.append('	};')
pbx.append('	rootObject = ' + ids['project'] + ' /* Project object */;')
pbx.append('}')

# Fix: g() used same dict key - c_t_app is duplicate with c_t_app - the ids use 'c_t_app' for cplist and config - I mixed variable names. Regenerate with unique keys.

# The script was incorrect - c_t_app used twice. Let me fix the ids dict
ids['c_t_app'] = g()  # list for app target
ids['c_t_test'] = g()
ids['clist_app'] = ids['c_t_app']
ids['c_t_app']  # oops
PY

# Fix the script: I'll output fixed version
pass
