"""Google Drive sign-in and image selection.

Use desktop Installed App OAuth with read-only permission. The first run opens
the browser; later runs reuse credentials/token.json.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

IMAGE_MIMES = "mimeType contains 'image/'"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_RE = re.compile(r"(?:folders/|id=)([a-zA-Z0-9_-]+)")


@dataclass(frozen=True)
class DriveImage:
    file_id: str
    name: str
    modified: str
    size_bytes: int


class DriveSetupError(RuntimeError):
    pass


def credentials_dir(project_root: Path) -> Path:
    path = project_root / "credentials"
    path.mkdir(exist_ok=True)
    return path


def find_client_secret(project_root: Path) -> Path:
    folder = credentials_dir(project_root)
    preferred = folder / "client_secret.json"
    if preferred.is_file():
        return preferred
    json_files = sorted(folder.glob("*.json"))
    secrets = [path for path in json_files if path.name != "token.json"]
    if not secrets:
        raise DriveSetupError(
            "Missing Google OAuth client file.\n"
            f"Place your Desktop OAuth client JSON at: {preferred}\n"
            "See the Google Drive section in README."
        )
    return secrets[0]


def connect(project_root: Path):
    """Open the browser on first use and return a Drive API service."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DriveSetupError(
            "Install dependencies first: python -m pip install -r requirements.txt\n"
            f"missing package: {exc}"
        ) from exc

    secret = find_client_secret(project_root)
    token_path = credentials_dir(project_root) / "token.json"
    creds = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds is None or not creds.valid:
        if creds is not None and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
            # Open the system browser for the user to grant read-only access to their Google account.
            creds = flow.run_local_server(port=0, open_browser=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_images(service, page_size: int = 20, folder_id: str | None = None) -> list[DriveImage]:
    query = f"{IMAGE_MIMES} and trashed = false"
    if folder_id:
        query = f"'{folder_id}' in parents and {query}"
    response = (
        service.files()
        .list(
            q=query,
            pageSize=page_size,
            orderBy="modifiedTime desc",
            fields="files(id, name, modifiedTime, size, mimeType)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    images = []
    for item in response.get("files", []):
        images.append(
            DriveImage(
                file_id=item["id"],
                name=item.get("name", item["id"]),
                modified=item.get("modifiedTime", ""),
                size_bytes=int(item.get("size", 0) or 0),
            )
        )
    return images


def download_image(service, file_id: str, dest: Path) -> Path:
    from googleapiclient.http import MediaIoBaseDownload

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    dest.write_bytes(buffer.getvalue())
    return dest


def parse_folder_id(text: str) -> str | None:
    match = FOLDER_RE.search(text.strip())
    if match:
        return match.group(1)
    # The user may paste a folder ID directly.
    token = text.strip()
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", token):
        return token
    return None


def choose_image(service, page_size: int, download_dir: Path) -> Path:
    """Terminal picker. A folder link lists that folder instead of recent files."""
    folder_id = None
    while True:
        images = list_images(service, page_size=page_size, folder_id=folder_id)
        if not images:
            print("No images here.")
        else:
            where = "Folder" if folder_id else "Recent images"
            print(f"\n{where}:")
            for index, image in enumerate(images, start=1):
                size_kb = image.size_bytes / 1024.0
                print(f"  {index:2d}. {image.name}   {image.modified[:19]}   {size_kb:.0f} KB")
        print()
        print("Enter a number to download")
        print("Or paste a Google Drive folder link")
        print("q: quit")
        choice = input("> ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            raise SystemExit(0)
        folder = parse_folder_id(choice)
        if folder and not choice.isdigit():
            folder_id = folder
            continue
        if choice.isdigit():
            number = int(choice)
            if 1 <= number <= len(images):
                image = images[number - 1]
                safe_name = Path(image.name).name or "drive_image.jpg"
                dest = download_dir / f"{image.file_id[:8]}_{safe_name}"
                print(f"Downloading {image.name}")
                return download_image(service, image.file_id, dest)
        print("Not a valid choice")
