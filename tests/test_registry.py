"""Test script for toolset registry.

This tests that the ToolsetManager correctly:
1. Retrieves individual toolsets
2. Combines multiple toolsets
3. Handles invalid toolset names
4. Works with the global instance
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.registry import ToolsetManager, get_toolset_manager
from pydantic_ai import FunctionToolset


def test_individual_toolset_retrieval():
    """Test getting individual toolsets by name."""
    print("Test 1: Individual Toolset Retrieval")
    print("-" * 50)

    manager = ToolsetManager()

    # Test each domain toolset
    catalog = manager.get("catalog")
    customers = manager.get("customers")
    conversations = manager.get("conversations")
    collab = manager.get("collab")

    print(f"✓ catalog toolset: {type(catalog).__name__}")
    print(f"✓ customers toolset: {type(customers).__name__}")
    print(f"✓ conversations toolset: {type(conversations).__name__}")
    print(f"✓ collab toolset: {type(collab).__name__}")

    # Verify they're not empty
    assert catalog is not None
    assert customers is not None
    assert conversations is not None
    assert collab is not None

    print("\n✅ All individual toolsets retrieved successfully\n")


def test_invalid_toolset_name():
    """Test handling of invalid toolset names."""
    print("Test 2: Invalid Toolset Name Handling")
    print("-" * 50)

    manager = ToolsetManager()

    # Should return empty toolset for invalid name
    invalid = manager.get("nonexistent")

    print(f"✓ Invalid toolset returns: {type(invalid).__name__}")
    assert isinstance(invalid, FunctionToolset)

    print("✅ Invalid toolset name handled gracefully\n")


def test_toolset_combination():
    """Test combining multiple toolsets."""
    print("Test 3: Toolset Combination")
    print("-" * 50)

    manager = ToolsetManager()

    # Test combining multiple toolsets (sales agent pattern)
    sales_tools = manager.combine(["catalog", "customers", "collab"])

    print(f"✓ Combined 3 toolsets: {len(sales_tools)} toolsets returned")
    assert len(sales_tools) == 3
    assert all(toolset is not None for toolset in sales_tools)

    # Test combining different sets (support agent pattern)
    support_tools = manager.combine(["conversations", "customers"])

    print(f"✓ Combined 2 toolsets: {len(support_tools)} toolsets returned")
    assert len(support_tools) == 2

    # Test empty combination
    empty_tools = manager.combine([])

    print(f"✓ Empty combination: {len(empty_tools)} toolsets returned")
    assert len(empty_tools) == 0

    # Test combination with invalid name (should include empty toolset)
    mixed_tools = manager.combine(["catalog", "nonexistent", "customers"])

    print(f"✓ Mixed valid/invalid: {len(mixed_tools)} toolsets returned")
    assert len(mixed_tools) == 3

    print("✅ All toolset combinations work correctly\n")


def test_all_tools_master_list():
    """Test the ALL_TOOLS master toolset list."""
    print("Test 4: ALL_TOOLS Master List")
    print("-" * 50)

    manager = ToolsetManager()

    all_tools = manager.all_tools

    print(f"✓ ALL_TOOLS contains: {len(all_tools)} toolsets")
    assert isinstance(all_tools, list)
    assert len(all_tools) == 4  # catalog, customers, conversations, collab

    # Verify it's a list of toolsets
    for i, toolset in enumerate(all_tools):
        print(f"  {i + 1}. {type(toolset).__name__}")

    print("✅ ALL_TOOLS master list is correct\n")


def test_global_instance():
    """Test the global toolset manager instance."""
    print("Test 5: Global Instance")
    print("-" * 50)

    manager1 = get_toolset_manager()
    manager2 = get_toolset_manager()

    print(f"✓ Global instance 1: {id(manager1)}")
    print(f"✓ Global instance 2: {id(manager2)}")

    # Should be the same instance
    assert manager1 is manager2
    print("✅ Global instance is singleton\n")


def test_real_world_scenarios():
    """Test real-world agent toolset configurations."""
    print("Test 6: Real-World Agent Scenarios")
    print("-" * 50)

    manager = ToolsetManager()

    # Sales agent: needs catalog, customers, and collaboration
    print("Sales Agent:")
    sales_tools = manager.combine(["catalog", "customers", "collab"])
    print(f"  ✓ {len(sales_tools)} toolsets: catalog, customers, collab")

    # Support agent: needs conversations and customers
    print("Support Agent:")
    support_tools = manager.combine(["conversations", "customers"])
    print(f"  ✓ {len(support_tools)} toolsets: conversations, customers")

    # Inventory specialist: only needs catalog (no collab)
    print("Inventory Specialist:")
    inventory_tools = manager.combine(["catalog"])
    print(f"  ✓ {len(inventory_tools)} toolset: catalog only")

    # Legal agent: minimal tools (just customers for context)
    print("Legal Agent:")
    legal_tools = manager.combine(["customers"])
    print(f"  ✓ {len(legal_tools)} toolset: customers only")

    print("\n✅ All real-world scenarios configured correctly\n")


def run_all_tests():
    """Run all registry tests."""
    print("=" * 50)
    print("TOOLSET REGISTRY TESTS")
    print("=" * 50)
    print()

    try:
        test_individual_toolset_retrieval()
        test_invalid_toolset_name()
        test_toolset_combination()
        test_all_tools_master_list()
        test_global_instance()
        test_real_world_scenarios()

        print("=" * 50)
        print("✅ ALL TESTS PASSED")
        print("=" * 50)
        return True

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
