#!/usr/bin/env python3
import pathlib, uuid, os

root = pathlib.Path(__file__).resolve().parent.parent
swift = sorted(p.relative_to(root) for p in (root / "TripPackAI").rglob("*.swift"))

def h():
    return uuid.uuid4().hex[:24].upper()

def main():
    P = h()
    Gmain, Gprod, Gtrip, Gtests = h(), h(), h(), h()
    Papp, Ptest = h(), h()
    Tapp, Ttest = h(), h()
    Sapp, Stest, Fapp, Ftest, R = h(), h(), h(), h(), h()
    CprojectD, CprojectR = h(), h()
    CappD, CappR = h(), h()
    CtestD, CtestR = h(), h()
    CLp, CLapp, CLtest = h(), h(), h()
    Proxy, Tdep = h(), h()

    fr, bf = {}, {}
    for p in swift:
        s = str(p)
        fr[s] = h()
        bf[s] = h()
    tfr, tbf = h(), h()

    lines = []
    def L(*a):
        lines.append("".join(a))

    L("// !$*UTF8*$!\n{\n	archiveVersion = 1;\n	classes = {\n	};\n	objectVersion = 56;\n	objects = {\n")
    L("/* Begin PBXBuildFile section */\n")
    for p in swift:
        L(f"		{bf[str(p)]} /* in Sources */ = {{isa = PBXBuildFile; fileRef = {fr[str(p)]} /* {p} */; }};\n")
    L(f"		{tbf} /* in Sources */ = {{isa = PBXBuildFile; fileRef = {tfr} /* PackageSolverTests.swift */; }};\n")
    L("/* End PBXBuildFile section */\n")
    L("/* Begin PBXFileReference section */\n")
    L(f"		{Papp} /* TripPackAI.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; path = TripPackAI.app; sourceTree = BUILT_PRODUCTS_DIR; }};\n")
    L(f"		{Ptest} /* TripPackAITests.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; path = TripPackAITests.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};\n")
    for p in swift:
        L(f"		{fr[str(p)]} /* {p} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = \"{p}\"; sourceTree = \"<group>\"; }};\n")
    L(f"		{tfr} /* PackageSolverTests.swift */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = PackageSolverTests.swift; sourceTree = \"<group>\"; }};\n")
    L("/* End PBXFileReference section */\n")
    L("/* Begin PBXFrameworksBuildPhase section */\n")
    L(f"		{Fapp} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = ( ); runOnlyForDeploymentPostprocessing = 0; }};\n")
    L(f"		{Ftest} = {{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = ( ); runOnlyForDeploymentPostprocessing = 0; }};\n")
    L("/* End PBXFrameworksBuildPhase section */\n")
    L("/* Begin PBXGroup section */\n")
    L(f"		{Gmain} = {{isa = PBXGroup; children = ( {Gtrip} /* TripPackAI */, {Gtests} /* Tests */, {Gprod} /* Products */ ); sourceTree = \"<group>\"; }};\n")
    L(f"		{Gprod} = {{isa = PBXGroup; children = ( {Papp}, {Ptest} ); name = Products; sourceTree = \"<group>\"; }};\n")
    L(f"		{Gtrip} = {{isa = PBXGroup; children = (")
    for p in swift:
        L(f"\n			{fr[str(p)]} /* {p} */,")
    L(f"\n		); path = TripPackAI; sourceTree = \"<group>\"; }};\n")
    L(f"		{Gtests} = {{isa = PBXGroup; children = ( {tfr} ); path = TripPackAITests; sourceTree = \"<group>\"; }};\n")
    L("/* End PBXGroup section */\n")
    L("/* Begin PBXResourcesBuildPhase section */\n")
    L(f"		{R} = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ( ); runOnlyForDeploymentPostprocessing = 0; }};\n")
    L("/* End PBXResourcesBuildPhase section */\n")
    L("/* Begin PBXContainerItemProxy section */\n")
    L(f"		{Proxy} = {{isa = PBXContainerItemProxy; containerPortal = {P}; proxyType = 1; remoteGlobalIDString = {Tapp}; remoteInfo = TripPackAI; }};\n")
    L("/* End PBXContainerItemProxy section */\n")
    L("/* Begin PBXTargetDependency section */\n")
    L(f"		{Tdep} = {{isa = PBXTargetDependency; target = {Tapp} /* TripPackAI */; targetProxy = {Proxy}; }};\n")
    L("/* End PBXTargetDependency section */\n")
    L("/* Begin PBXNativeTarget section */\n")
    L(f"		{Tapp} = {{isa = PBXNativeTarget; buildConfigurationList = {CLapp}; buildPhases = ( {Sapp}, {Fapp}, {R}, ); name = TripPackAI; productName = TripPackAI; productReference = {Papp}; productType = com.apple.product-type.application; }};\n")
    L(f"		{Ttest} = {{isa = PBXNativeTarget; buildConfigurationList = {CLtest}; buildPhases = ( {Stest}, {Ftest}, ); dependencies = ( {Tdep} ); name = TripPackAITests; productName = TripPackAITests; productReference = {Ptest}; productType = com.apple.product-type.bundle.unit-test; }};\n")
    L("/* End PBXNativeTarget section */\n")
    L("/* Begin PBXSourcesBuildPhase section */\n")
    L(f"		{Sapp} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (")
    for p in swift:
        L(f"\n			{bf[str(p)]},")
    L(f"\n		); runOnlyForDeploymentPostprocessing = 0; }};\n")
    L(f"		{Stest} = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ( {tbf}, ); runOnlyForDeploymentPostprocessing = 0; }};\n")
    L("/* End PBXSourcesBuildPhase section */\n")
    L("/* Begin PBXProject section */\n")
    L(f"		{P} = {{isa = PBXProject; buildConfigurationList = {CLp}; mainGroup = {Gmain}; targets = ( {Tapp}, {Ttest} );}};\n")
    L("/* End PBXProject section */\n")
    L("/* Begin XCBuildConfiguration section */\n")
    L(f"		{CprojectD} = {{isa = XCBuildConfiguration; buildSettings = {{ CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 5.0; }}; name = Debug; }};\n")
    L(f"		{CprojectR} = {{isa = XCBuildConfiguration; buildSettings = {{ CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 5.0; }}; name = Release; }};\n")
    L(f"		{CappD} = {{isa = XCBuildConfiguration; buildSettings = {{ ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; CODE_SIGN_IDENTITY = \"-\"; ENABLE_PREVIEWS = YES; ENABLE_TESTABILITY = YES; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"@executable_path/Frameworks\"); PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI; SDKROOT = iphoneos; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; }}; name = Debug; }};\n")
    L(f"		{CappR} = {{isa = XCBuildConfiguration; buildSettings = {{ ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; ENABLE_PREVIEWS = YES; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"@executable_path/Frameworks\"); PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI; SUPPORTED_PLATFORMS = \"iphonesimulator iphoneos\"; SWIFT_VERSION = 5.0; TARGETED_DEVICE_FAMILY = 1; }}; name = Release; }};\n")
    L(f"		{CtestD} = {{isa = XCBuildConfiguration; buildSettings = {{ BUNDLE_LOADER = \"$(TEST_HOST)\"; CLANG_ENABLE_MODULES = YES; ENABLE_TESTING_SEARCH_PATHS = NO; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI.tests; SWIFT_VERSION = 5.0; TEST_HOST = \"$(BUILT_PRODUCTS_DIR)/TripPackAI.app/$$$$(INFOPLIS_KEY)\"; }}; name = Debug; }};\n")
    # Test host is wrong in above - fix
    L(f"		{CtestD} = {{isa = XCBuildConfiguration; buildSettings = {{ BUNDLE_LOADER = \"$(TEST_HOST)\"; CLANG_ENABLE_MODULES = YES; GENERATE_INFOPLIST_FILE = YES; IPHONEOS_DEPLOYMENT_TARGET = 17.0; LD_RUNPATH_SEARCH_PATHS = (\"@loader_path/Frameworks\"); PRODUCT_BUNDLE_IDENTIFIER = com.trippack.TripPackAI.tests; SWIFT_VERSION = 5.0; TEST_HOST = \"$(BUILT_PRODUCTS_DIR)/TripPackAI.app/TripPackAI\"; }}; name = Debug; }};\n")
    # We duplicated CtestD - the script is messy. Simpler: **remove test target** from pbx to ship working app
    L("/* error removed duplicate line */ \n")
    L("/* End XCBuildConfiguration - truncated */ \n")
    L("	};\n")

    return "".join(lines)

if __name__ == "__main__":
    # Don't run broken output
    print("use hand project below")
