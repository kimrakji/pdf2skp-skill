"""Copy the local plugin and register it in a personal marketplace."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile


PLUGIN_NAME = "interior-os"
SOURCE_PATH = f"./.codex/plugins/{PLUGIN_NAME}"


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def install(target_root):
    package_root = Path(__file__).resolve().parents[1]
    manifest = read_json(package_root / "plugin.json")
    if manifest.get("name") != PLUGIN_NAME:
        raise ValueError("패키지의 plugin.json 이름을 확인하세요.")
    if not (package_root / "skills/pdf-to-sketchup/SKILL.md").is_file():
        raise ValueError("패키지에 PDF to SketchUp Skill이 없습니다.")

    target = target_root / ".codex/plugins" / PLUGIN_NAME
    catalog_path = target_root / ".agents/plugins/marketplace.json"
    if target.is_symlink() or catalog_path.is_symlink():
        raise ValueError("설치 대상이 심볼릭 링크입니다. 실제 경로를 먼저 확인하세요.")
    if target.exists():
        existing = read_json(target / "plugin.json")
        if existing.get("name") != PLUGIN_NAME:
            raise ValueError("같은 경로에 다른 패키지가 있습니다. 기존 파일을 보존합니다.")

    catalog = (
        read_json(catalog_path)
        if catalog_path.exists()
        else {
            "name": "interior-os-local",
            "interface": {"displayName": "Interior OS Local"},
            "plugins": [],
        }
    )
    if not isinstance(catalog, dict) or not isinstance(catalog.get("name"), str):
        raise ValueError("기존 marketplace.json의 형식이 올바르지 않습니다.")
    plugins = catalog.get("plugins")
    if not isinstance(plugins, list) or any(not isinstance(item, dict) for item in plugins):
        raise ValueError("기존 marketplace.json의 plugins 목록을 확인하세요.")
    matches = [item for item in plugins if item.get("name") == PLUGIN_NAME]
    if len(matches) > 1:
        raise ValueError("기존 목록에 Interior OS 항목이 중복되어 있습니다.")
    source = {"source": "local", "path": SOURCE_PATH}
    if matches and matches[0].get("source") not in (source, SOURCE_PATH):
        raise ValueError("기존 Interior OS 항목이 다른 경로를 가리킵니다. 기존 설정을 보존합니다.")
    if not matches:
        plugins.append(
            {
                "name": PLUGIN_NAME,
                "source": source,
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        )

    payload = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    changed = not catalog_path.exists() or read_json(catalog_path) != catalog
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    if changed and catalog_path.exists():
        with tempfile.NamedTemporaryFile(
            prefix="marketplace.json.backup-", dir=catalog_path.parent, delete=False
        ) as backup:
            backup_path = Path(backup.name)
        shutil.copy2(catalog_path, backup_path)
        print(f"기존 목록 백업: {backup_path}")

    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package_root / "plugin.json", target / "plugin.json")
    shutil.copytree(
        package_root / "skills",
        target / "skills",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    if changed:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="marketplace-", dir=catalog_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, catalog_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    interface = catalog.get("interface")
    marketplace_label = (
        interface.get("displayName", catalog["name"])
        if isinstance(interface, dict)
        else catalog["name"]
    )
    print(f"플러그인 소스: {target}")
    print(f"마켓플레이스: {marketplace_label} ({catalog['name']})")
    print("ChatGPT 데스크톱 앱을 재시작한 뒤 Plugins에서 Interior OS를 설치하세요.")
    print("이 명령은 목록 등록만 수행합니다. 앱 설치와 Python/SketchUp 실행은 별도 확인합니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-root", type=Path, default=Path.home(),
        help="개인 목록의 루트 경로. 기본값은 홈 폴더이며, 다른 경로는 설치 시험용입니다.",
    )
    args = parser.parse_args()
    try:
        install(args.target_root.expanduser().resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, f"설치 중단: {error}\n")


if __name__ == "__main__":
    main()
