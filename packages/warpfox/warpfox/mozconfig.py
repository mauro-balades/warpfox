BASIC_BUILD_CONFIG = """
ac_add_options --enable-application=browser
ac_add_options --enable-bootstrap

# ccache
ac_add_options --with-ccache
ac_add_options --with-branding=browser/branding/unofficial

MOZ_APP_NAME=test
"""


def get_mozconfig_contents():
    return "\n".join(
        [
            BASIC_BUILD_CONFIG,
        ]
    )
