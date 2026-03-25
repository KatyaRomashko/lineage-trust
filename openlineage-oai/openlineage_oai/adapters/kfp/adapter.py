"""
KFP adapter for OpenLineage.

Unlike MLflow (which has a plugin system), KFP v2 has no hook mechanism.
The adapter registers itself with the openlineage-oai framework but the
actual lineage emission happens via the ``kfp_lineage`` context manager
that users import inside their ``@dsl.component`` functions.
"""

from openlineage_oai.adapters.base import ToolAdapter


class KFPAdapter(ToolAdapter):
    """KFP adapter using an in-component context manager.

    ``install_hooks()`` verifies that KFP is importable but does not
    monkey-patch anything.  The real integration is the ``kfp_lineage``
    context manager in ``lineage.py``, which users call explicitly from
    inside their component code.
    """

    def get_tool_name(self) -> str:
        return "kfp"

    def install_hooks(self) -> None:
        """Verify KFP is available.  No runtime patching is performed."""
        try:
            import kfp  # noqa: F401

            self._installed = True
        except ImportError as e:
            raise ImportError(
                "KFP is not installed. Install it with: pip install kfp"
            ) from e

    def uninstall_hooks(self) -> None:
        """No-op — there are no hooks to remove."""
        self._installed = False
