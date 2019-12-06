FILE_50K = "data/samples/SampleImage_50kb.jpg"
FILE_100K = "data/samples/SampleImage_50kb.jpg"


def load_file50k() -> bytes:
    return load_file(FILE_50K)


def load_file100k() -> bytes:
    return load_file(FILE_100K)


def load_file(path) -> bytes:
    with open(path, "rb") as file:
        content = file.read()
    return content
