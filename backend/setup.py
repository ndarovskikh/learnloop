from setuptools import find_packages, setup


setup(
    name="learnloop",
    version="0.1.0",
    description="Adaptive agent loop for course learning",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=[
        "fastapi>=0.115.0",
        "openai>=1.30.0",
        "uvicorn>=0.30.0",
    ],
    entry_points={
        "console_scripts": [
            "learnloop=learnloop.cli:main",
            "learnloop-api=learnloop.api:run",
        ]
    },
)
