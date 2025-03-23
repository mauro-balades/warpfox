BASIC_BUILD_CONFIG = """
ac_add_options --enable-application=browser_artifact_mode

# For faster builds
ac_add_options --enable-artifact-builds
"""


def get_mozconfig_contents():
    return "\n".join(
        [
            BASIC_BUILD_CONFIG,
        ]
    )
