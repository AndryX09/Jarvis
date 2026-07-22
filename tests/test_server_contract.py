import ast
import unittest
from pathlib import Path


class ServerContractTests(unittest.TestCase):
    def test_server_exposes_v133_policy_contract_without_delete_tool(self):
        server_path = Path(__file__).resolve().parents[1] / "app" / "server.py"
        source = server_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        tool_names = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "mcp"
                    and target.attr == "tool"
                ):
                    tool_names.append(node.name)

        self.assertIn('"Jarvis Core v1.3.3"', source)
        self.assertEqual(len(tool_names), 23)
        self.assertIn("read_organization_policy", tool_names)
        self.assertIn("read_ingestion_policy", tool_names)
        self.assertFalse(any("delete" in name for name in tool_names))

    def test_update_capture_status_schema_requires_summary(self):
        server_path = Path(__file__).resolve().parents[1] / "app" / "server.py"
        tree = ast.parse(server_path.read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "update_capture_status"
        )
        positional = [*function.args.posonlyargs, *function.args.args]
        required_count = len(positional) - len(function.args.defaults)
        required_names = {argument.arg for argument in positional[:required_count]}

        self.assertIn("summary", required_names)


if __name__ == "__main__":
    unittest.main()
