"""
Tests for the Security Policy Engine.
"""

import pytest
from aider.security.policy import PolicyEngine, SecurityViolation

def test_secret_scanner():
    engine = PolicyEngine()
    
    # Generic API Key
    content = "API_KEY = 'abcdef1234567890' # Secret key"
    result = engine.scan(content)
    assert not result.success
    assert any("Generic API Key" in v.message for v in result.violations)
    
    # AWS Key
    content = "AWS_ACCESS_KEY = 'AKIA1234567890ABCDEF'"
    result = engine.scan(content)
    assert not result.success
    assert any("AWS Access Key" in v.message for v in result.violations)

def test_unsafe_shell():
    engine = PolicyEngine()
    
    # shell=True
    content = "subprocess.run('ls', shell=True)"
    result = engine.scan(content)
    assert not result.success
    assert any("shell=True" in v.message for v in result.violations)
    
    # os.system
    content = "os.system('rm -rf /')"
    result = engine.scan(content)
    assert not result.success
    assert any("os.system" in v.message for v in result.violations)

def test_path_traversal():
    engine = PolicyEngine()
    
    # ../
    content = "with open('../../etc/passwd') as f:"
    result = engine.scan(content)
    assert not result.success
    assert any("path traversal" in v.message.lower() for v in result.violations)
    
    # Sensitive file
    content = "target = '/etc/shadow'"
    result = engine.scan(content)
    assert not result.success
    assert any("sensitive system file" in v.message.lower() for v in result.violations)

def test_safe_content():
    engine = PolicyEngine()
    content = "print('Hello, world!')\nx = 1 + 2\n"
    result = engine.scan(content)
    assert result.success
    assert len(result.violations) == 0

if __name__ == "__main__":
    pytest.main([__file__])
