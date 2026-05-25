import pytest
import tempfile
import pathlib
from ouroboros.semantic_memory import SemanticMemory


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = pathlib.Path(tmpdir) / "test.db"
        yield db_path


@pytest.fixture
def memory(temp_db):
    """Create SemanticMemory instance."""
    mem = SemanticMemory(temp_db)
    yield mem
    mem.close()


def test_add_memory(memory):
    """Test adding a memory."""
    memory_id = memory.add_memory(
        "Ouroboros is a self-developing AI agent",
        metadata={"type": "fact"},
        tags=["ai", "agent"],
    )
    assert memory_id > 0


def test_entity_extraction(memory):
    """Test entity extraction from text."""
    text = "Alice and Bob met in New York on 2026-05-25"
    entities = memory._extract_entities(text)
    assert "Alice" in entities
    assert "Bob" in entities
    assert "New" in entities
    assert "York" in entities
    assert "2026" in entities
    assert "05" in entities
    assert "25" in entities


def test_get_memories(memory):
    """Test searching memories by keyword."""
    memory.add_memory("Python is a programming language")
    memory.add_memory("JavaScript is also a programming language")
    memory.add_memory("Rust is a systems programming language")
    
    results = memory.get_memories("Python", limit=5)
    assert len(results) > 0
    assert any("Python" in r["text"] for r in results)


def test_search_by_entity(memory):
    """Test searching by entity."""
    memory.add_memory("Alice works at Google")
    memory.add_memory("Bob works at Microsoft")
    
    results = memory.search_by_entity("Alice", limit=5)
    assert len(results) > 0
    assert "Alice" in results[0]["text"]


def test_get_recent(memory):
    """Test getting recent memories."""
    memory.add_memory("First memory")
    memory.add_memory("Second memory")
    memory.add_memory("Third memory")
    
    results = memory.get_recent(limit=2)
    assert len(results) == 2
    assert "Third" in results[0]["text"]
    assert "Second" in results[1]["text"]


def test_metadata_storage(memory):
    """Test metadata is stored and retrieved correctly."""
    metadata = {"source": "user", "importance": "high"}
    memory_id = memory.add_memory("Test memory", metadata=metadata)
    
    results = memory.get_recent(limit=1)
    assert results[0]["metadata"] == metadata
