from os.path import exists, join

from pythonforandroid.logger import info

# NOTE:
# python-for-android's `sdl2_image` recipe changed its exported symbol names
# over time. Some releases export `SDL2ImageRecipe`, others only expose a
# `recipe = ...` instance. This local override needs to work with both.
import pythonforandroid.recipes.sdl2_image as _upstream_sdl2_image


def _get_upstream_recipe_class():
    # Old p4a versions.
    cls = getattr(_upstream_sdl2_image, "SDL2ImageRecipe", None)
    if cls is not None:
        return cls

    # Newer p4a versions may only expose an instantiated `recipe`.
    upstream_recipe = getattr(_upstream_sdl2_image, "recipe", None)
    if upstream_recipe is not None:
        return upstream_recipe.__class__

    # Best-effort fallback for any other naming variant.
    for name in (
        "SDL2_imageRecipe",
        "Sdl2ImageRecipe",
        "SDL2imageRecipe",
        "SDL2Image",
    ):
        cls = getattr(_upstream_sdl2_image, name, None)
        if cls is not None:
            return cls

    raise ImportError(
        "Unsupported python-for-android version: cannot locate upstream "
        "sdl2_image recipe class (expected `SDL2ImageRecipe` or `recipe`)."
    )


class SDL2ImageRecipe(_get_upstream_recipe_class()):
    def apply_patches(self, arch):
        # This repo overrides the upstream recipe but doesn't necessarily carry
        # all upstream patch files. Newer p4a versions include e.g.
        # `enable-webp.patch`; if it's not present locally, skip it rather than
        # failing the whole build.
        patches = list(getattr(self, "patches", []) or [])
        if patches:
            existing = [p for p in patches if exists(join(self.recipe_dir, p))]
            missing = [p for p in patches if p not in set(existing)]
            if missing:
                info(f"sdl2_image: skipping missing patches: {', '.join(missing)}")
            self.patches = existing
        return super().apply_patches(arch)

    def prebuild_arch(self, arch):
        build_dir = self.get_build_dir(arch.arch)
        external_dir = join(build_dir, "external")
        marker_path = join(external_dir, ".p4a_external_downloaded")

        if exists(marker_path):
            info("sdl2_image: external deps already downloaded; skipping download.sh")
            return

        legacy_jpeg_paths = (
            join(external_dir, "external", "jpeg"),
            join(external_dir, "jpeg"),
        )
        if any(exists(path) for path in legacy_jpeg_paths):
            info("sdl2_image: external deps already present; skipping download.sh")
            _touch_marker(marker_path)
            return

        super().prebuild_arch(arch)
        _touch_marker(marker_path)


def _touch_marker(path):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ok\n")
    except OSError:
        # Best-effort marker; build should not fail on write issues.
        pass


recipe = SDL2ImageRecipe()
