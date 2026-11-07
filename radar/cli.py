import argparse
import getpass
import os
import re
import secrets
from pathlib import Path

from alembic import command
from alembic.config import Config

from .security import hash_password


def main():
    parser = argparse.ArgumentParser(description="初始化 ChannelRadar 工作台")
    parser.add_argument("command", choices=["init", "migrate", "password"])
    parser.add_argument("--generate", action="store_true", help="随机生成初始密码并保存本机凭据文件")
    parser.add_argument("--local", action="store_true", help="本机 HTTP 调试，关闭 Secure cookie")
    args = parser.parse_args()
    Path("data").mkdir(exist_ok=True)
    if args.command == "password":
        config = Path(".env")
        if not config.is_file():
            parser.error("请先初始化 .env")
        password = getpass.getpass("设置新密码（至少 12 位） ")
        if len(password) < 12 or password != getpass.getpass("再次输入密码 "):
            parser.error("密码长度不足或两次输入不一致")
        content, count = re.subn(
            r"(?m)^RADAR_ADMIN_PASSWORD_HASH=.*$",
            lambda _: f"RADAR_ADMIN_PASSWORD_HASH='{hash_password(password)}'",
            config.read_text(encoding="utf-8"),
        )
        if count != 1:
            parser.error(".env 必须包含唯一的管理员密码哈希")
        temporary = config.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(config)
        print("密码已更新，重启服务后生效")
        return
    if args.command == "init":
        if Path(".env").exists():
            parser.error(".env 已存在，请用 migrate 升级数据库")
        password = secrets.token_urlsafe(20) if args.generate else getpass.getpass("设置管理员密码（至少 12 位） ")
        if len(password) < 12:
            parser.error("密码至少需要 12 位")
        if not args.generate and password != getpass.getpass("再次输入密码 "):
            parser.error("两次密码不一致")
        values = {
            "RADAR_DATABASE_URL": "sqlite:///data/workbench.sqlite3",
            "RADAR_ADMIN_USERNAME": "admin",
            "RADAR_ADMIN_PASSWORD_HASH": hash_password(password),
            "RADAR_SESSION_SECRET": secrets.token_urlsafe(48),
            "RADAR_POSTGRES_PASSWORD": secrets.token_urlsafe(24),
            "RADAR_COOKIE_SECURE": "false" if args.local else "true",
        }
        Path(".env").write_text("".join(f"{key}='{value}'\n" for key, value in values.items()), encoding="utf-8")
        os.chmod(".env", 0o600)
        if args.generate:
            credentials = Path("data/admin-initial.txt")
            credentials.write_text(f"用户名 admin\n初始密码 {password}\n请妥善保存，复制后删除此文件。\n", encoding="utf-8")
            os.chmod(credentials, 0o600)
            print("随机登录信息已写入 data/admin-initial.txt")
    command.upgrade(Config("alembic.ini"), "head")
    print("工作台数据库已就绪")


if __name__ == "__main__":
    main()
