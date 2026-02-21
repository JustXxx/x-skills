"""
macOS clipboard operations via Swift/AppKit.

Compiles Swift source code to a binary that can write images or HTML
to the macOS system clipboard. The binary is cached using MD5 hash
of the source to avoid recompilation.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.cache/x-poster/clipboard")

# Swift source for image clipboard operations
SWIFT_IMAGE_SOURCE = """\
import AppKit
import Foundation

let args = CommandLine.arguments
guard args.count >= 2 else {
    fputs("Usage: clipboard-image <image-path>\\n", stderr)
    exit(1)
}

let imagePath = args[1]
guard let image = NSImage(contentsOfFile: imagePath) else {
    fputs("Error: Cannot load image: \\(imagePath)\\n", stderr)
    exit(1)
}

let pb = NSPasteboard.general
pb.clearContents()

guard let tiffData = image.tiffRepresentation,
      let bitmapRep = NSBitmapImageRep(data: tiffData),
      let pngData = bitmapRep.representation(using: .png, properties: [:]) else {
    fputs("Error: Cannot convert image to PNG\\n", stderr)
    exit(1)
}

pb.setData(pngData, forType: .png)
pb.setData(tiffData, forType: .tiff)

// Also set as fileURL for paste compatibility
let fileURL = URL(fileURLWithPath: imagePath)
pb.writeObjects([fileURL as NSURL])

print("Image copied to clipboard: \\(imagePath)")
"""

# Swift source for HTML clipboard operations
SWIFT_HTML_SOURCE = """\
import AppKit
import Foundation

let args = CommandLine.arguments
guard args.count >= 2 else {
    fputs("Usage: clipboard-html <html-string-or-file-path>\\n", stderr)
    exit(1)
}

var htmlContent: String
let input = args[1]

if input == "--file" && args.count >= 3 {
    let filePath = args[2]
    guard let data = FileManager.default.contents(atPath: filePath),
          let content = String(data: data, encoding: .utf8) else {
        fputs("Error: Cannot read file: \\(filePath)\\n", stderr)
        exit(1)
    }
    htmlContent = content
} else {
    htmlContent = input
}

let pb = NSPasteboard.general
pb.clearContents()

// Set HTML
if let htmlData = htmlContent.data(using: .utf8) {
    pb.setData(htmlData, forType: .html)
}

// Also set as RTF for rich text paste compatibility
if let attrStr = try? NSAttributedString(
    data: htmlContent.data(using: .utf8)!,
    options: [.documentType: NSAttributedString.DocumentType.html,
              .characterEncoding: String.Encoding.utf8.rawValue],
    documentAttributes: nil
) {
    let rtfData = try? attrStr.data(
        from: NSRange(location: 0, length: attrStr.length),
        documentAttributes: [.documentType: NSAttributedString.DocumentType.rtf]
    )
    if let rtfData = rtfData {
        pb.setData(rtfData, forType: .rtf)
    }
}

// Set plain text fallback
pb.setString(htmlContent, forType: .string)

print("HTML copied to clipboard")
"""


def _get_cache_path(source: str, name: str) -> str:
    """Get the cache path for a compiled Swift binary.

    Args:
        source: Swift source code
        name: Binary name prefix

    Returns:
        Path to the cached binary
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    source_hash = hashlib.md5(source.encode()).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"{name}-{source_hash}")


def _ensure_compiled(source: str, name: str) -> str:
    """Compile Swift source to binary if not already cached.

    Args:
        source: Swift source code
        name: Binary name prefix

    Returns:
        Path to the compiled binary

    Raises:
        RuntimeError: If compilation fails
    """
    binary_path = _get_cache_path(source, name)

    if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
        logger.debug("Using cached binary: %s", binary_path)
        return binary_path

    logger.info("Compiling Swift clipboard helper: %s", name)

    # Write source to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".swift", delete=False
    ) as f:
        f.write(source)
        source_file = f.name

    try:
        result = subprocess.run(
            ["swiftc", "-O", "-o", binary_path, source_file],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Swift compilation failed:\n{result.stderr}"
            )
        os.chmod(binary_path, 0o755)
        logger.info("Compiled: %s", binary_path)
        return binary_path
    finally:
        os.unlink(source_file)


def copy_image(image_path: str) -> None:
    """Copy an image file to the macOS system clipboard.

    Args:
        image_path: Path to the image file (PNG, JPEG, etc.)

    Raises:
        FileNotFoundError: If image file doesn't exist
        RuntimeError: If clipboard operation fails
    """
    image_path = os.path.abspath(image_path)
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    binary = _ensure_compiled(SWIFT_IMAGE_SOURCE, "clipboard-image")

    result = subprocess.run(
        [binary, image_path],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to copy image to clipboard: {result.stderr}"
        )
    logger.debug("Image copied to clipboard: %s", image_path)


def copy_html(html: str, from_file: bool = False) -> None:
    """Copy HTML content to the macOS system clipboard.

    Sets HTML, RTF, and plain text representations.

    Args:
        html: HTML string or file path (if from_file=True)
        from_file: If True, treat html as a file path

    Raises:
        RuntimeError: If clipboard operation fails
    """
    binary = _ensure_compiled(SWIFT_HTML_SOURCE, "clipboard-html")

    if from_file:
        html_path = os.path.abspath(html)
        if not os.path.isfile(html_path):
            raise FileNotFoundError(f"HTML file not found: {html_path}")
        args = [binary, "--file", html_path]
    else:
        args = [binary, html]

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=15,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to copy HTML to clipboard: {result.stderr}"
        )
    logger.debug("HTML copied to clipboard")
