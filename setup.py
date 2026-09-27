from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).parent

setup(
    name="laptopguard",
    version="0.1.24",
    description="Linux anti-theft and laptop security agent for Linux Mint and Ubuntu",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    license="MIT",
    keywords=[
        "linux",
        "anti-theft",
        "laptop-security",
        "linux-mint",
        "ubuntu",
        "systemd",
        "geolocation",
        "webcam",
        "intrusion-detection",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Security",
        "Topic :: System :: Monitoring",
    ],
    packages=find_packages("src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.21",
        "opencv-python-headless>=4.5",
        "cryptography>=3.4",
        "tomli>=2; python_version<'3.11'",
    ],
    entry_points={"console_scripts": ["laptopguard=laptopguard.cli:main"]},
)
