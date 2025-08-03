#!/usr/bin/env python3
"""
Test script for the StyleService to verify that therapy styles are loaded correctly.
"""

import sys
import os

# Add the parent directory to the path so we can import the services
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

def test_style_service():
    """Test the StyleService functionality."""
    print("Testing StyleService...")
    
    # Import the style service directly
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "style_service", 
        os.path.join(os.path.dirname(__file__), "..", "src", "services", "style_service.py")
    )
    style_service_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(style_service_module)
    
    # Get the style service instance
    style_service = style_service_module.style_service
    
    # Print the styles directory path for debugging
    print(f"Styles directory path: {style_service.styles_dir}")
    print(f"Styles directory exists: {style_service.styles_dir.exists()}")
    
    # Test loading available styles
    available_styles = style_service.get_available_styles()
    print(f"Available styles: {available_styles}")
    
    # Verify that our three main styles are loaded
    expected_styles = ['freud', 'jung', 'cbt']
    for style in expected_styles:
        if style in available_styles:
            print(f"✓ {style.upper()} style loaded successfully")
            
            # Test loading style components
            style_pack = style_service.get_style_pack(style)
            if style_pack:
                print(f"  - Knowledge length: {len(style_pack.knowledge)} characters")
                print(f"  - Description length: {len(style_pack.description)} characters")
                print(f"  - Psychoanalyst prompt length: {len(style_pack.psychoanalyst_prompt)} characters")
                print(f"  - Reflection prompt length: {len(style_pack.reflection_prompt)} characters")
                print(f"  - Assessment prompt length: {len(style_pack.assessment_prompt)} characters")
            else:
                print(f"  ✗ Style pack not found")
        else:
            print(f"✗ {style.upper()} style not found")
    
    # Test specific component retrieval
    print("\nTesting component retrieval...")
    for style in expected_styles:
        description = style_service.get_style_description(style)
        if description:
            print(f"✓ {style.upper()} description: {description[:50]}...")
        else:
            print(f"✗ {style.upper()} description not found")
    
    print("\nStyleService test completed!")

if __name__ == "__main__":
    test_style_service()
