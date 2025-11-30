import transformers
print(f"Transformers version: {transformers.__version__}")
try:
    from transformers import HunYuanVLForConditionalGeneration
    print("Direct import successful")
except ImportError:
    print("Direct import failed")
    print("Available in transformers:", [x for x in dir(transformers) if 'HunYuan' in x or 'Hunyuan' in x])

    try:
        # Try finding it in models subpackage if possible (though structure varies)
        import transformers.models.hunyuan_vl
        print("transformers.models.hunyuan_vl imported")
    except ImportError as e:
        print(f"Submodule import failed: {e}")

