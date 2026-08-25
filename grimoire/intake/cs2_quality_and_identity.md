# CS2 quality floors and item identity

Moved from the base skill's `grimoire/intake/quality_contract.md` and `validation_rubric.md` when CS2
became a plugin. The base states the general rule; this is the CS2-specific version of it.

Note: `--cs2` no longer exists on the base CLI. The floors below are published by this plugin's
`emit_spec_augmentation.py` and applied by the base's raise-only merge.

### CS2 items: ultra-complex by default

A CS2 weapon/knife/glove skin always carries more identity-defining detail (finish/gradient
pattern, wear layer, hardware, stitching, fasteners, engraving) than a generic object at the
same structural complexity tier — the skin *is* the point of the item. So `--cs2` **defaults
the complexity tier to `ultra-complex`** (`targetMinDetails` 16): the CS2 track is held to the
top fidelity bar regardless of how simple the bare geometry looks, and `--strict-quality` then
blocks code generation until those details are enumerated. If `--complexity` is set lower by
hand, `targetMinDetails` still never drops below the **9** floor. Pass `--cs2` to
`forge/stage2_spec/new_pre_spec_assessment.py` to apply this automatically.


## CS2 Item Identity and References (Critical — from Bowie Knife reconstruction)

**The problem:** `--cs2` only sets the difficulty tier; it does NOT fetch metadata or official references. Assuming stock features from skin names leads to wrong geometry (e.g., assuming "no stock Bowie has sawback" when the vanilla render proves it does).

**Rule:** Get the item's real market name/identity EARLY, and pull official references FIRST before authoring geometry:

1. **Ask the user for the exact market name** up front (e.g., "Autotronic" not just "Bowie Knife with red/black finish")
2. **Use `fetch_cs2_metadata.py`** to resolve paint index + official CDN render + confirm the skin exists
3. **Fetch official + vanilla renders** before authoring geometry — these show the base model features (sawback, clip point, tang, guard style) that skin names don't reveal
4. **Never infer stock features from skin names alone** — the vanilla render is the source of truth for base model geometry

**Reference sources:** Official CS2 CDN renders, vanilla (factory new) renders, and any official artwork provided by the user. Side-view orthographic reference images are ideal for profile extraction; 3/4 angle renders help verify form and materials.

**Verification:** Before writing geometry, confirm you have:
- Exact item name (market name, not description)
- Official vanilla render (to see base model features)
- Official skin render (to see finish/pattern)
- Any orthographic side views if available
