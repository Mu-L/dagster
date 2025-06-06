from dataclasses import dataclass

import dagster as dg


class HooliAssetCheck(dg.Model):
    asset: str
    check_name: str


@dataclass
class HooliAssetChecksComponent(dg.Component, dg.Resolvable):
    """COMPONENT SUMMARY HERE.

    COMPONENT DESCRIPTION HERE.
    """

    checks: list[HooliAssetCheck]

    def build_defs(self, context: dg.ComponentLoadContext) -> dg.Definitions:
        # Add definition construction logic here.
        def create_check_fn(hooli_asset_check: HooliAssetCheck) -> dg.AssetChecksDefinition:
            @dg.asset_check(
                asset=dg.AssetKey.from_user_string(hooli_asset_check.asset),
                name=hooli_asset_check.check_name,
            )
            def _check() -> dg.AssetCheckResult:
                return dg.AssetCheckResult(passed=True)

            return _check

        check_defs = []
        for check in self.checks:
            check_defs.append(create_check_fn(check))
        return dg.Definitions(asset_checks=check_defs)
