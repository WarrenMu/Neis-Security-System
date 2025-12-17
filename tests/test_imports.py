def test_imports() -> None:
    import gatewatch
    import gatewatch.main
    import gatewatch.pipeline
    import gatewatch.notify
    import gatewatch.storage
    import gatewatch.camera
    import gatewatch.detect
    import gatewatch.ocr

    assert gatewatch.__version__
