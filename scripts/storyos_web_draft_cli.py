"""Local Web drafts API; optional separate-secret canonical bootstrap, never Driver."""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

from platform.repository.mysql.web_draft_repository import WebDraftRepository, DraftWriteError
from platform.operations.web_draft_handoff_plan import compile_handoff_plan
from platform.operations.web_draft_execute_preflight import execute_saved_dry_run, PreflightBlocked
from platform.operations.web_draft_episode_bootstrap import bootstrap_saved_episode, BootstrapBlocked

BASE="/api/v1/web-drafts"
ITEM=re.compile(r"^/api/v1/web-drafts/(WDW_[a-f0-9-]{36})$")
HANDOFF=re.compile(r"^/api/v1/web-drafts/(WDW_[a-f0-9-]{36})/handoff-plan$")
PREFLIGHT=re.compile(r"^/api/v1/web-drafts/(WDW_[a-f0-9-]{36})/preflight$")
BOOTSTRAP=re.compile(r"^/api/v1/web-drafts/(WDW_[a-f0-9-]{36})/bootstrap$")
MAX=2_100_000

def main():
    try:
        test_only=os.environ.get("STORYOS_WEB_DRAFTS_TEST_ONLY")=="1"
        if not test_only and os.environ.get("STORYOS_WEB_DRAFTS_ENABLE")!="1":
            raise DraftWriteError("WEB_DRAFT_WRITER_DISABLED",403)
        path=os.environ.get("STORYOS_WEB_DRAFTS_AUTH","")
        if not Path(path).is_absolute():
            raise DraftWriteError("NO_AUTH_FILE",403)
        file=Path(path).resolve(strict=True)
        if file.name!="web-draft-auth.json" or file.parent.name!="web-drafts" or file.parent.parent.name!=".storyos-tmp":
            raise DraftWriteError("WRONG_AUTH_LOCATION",403)
        if file.stat().st_size>2048:
            raise DraftWriteError("AUTH_TOO_LARGE",403)
        config=json.loads(file.read_text(encoding="utf8"))
        raw=sys.stdin.buffer.read(MAX+1)
        if len(raw)>MAX:
            raise DraftWriteError("REQUEST_TOO_LARGE",413)
        command=json.loads(raw)
        if not isinstance(command,dict) or set(command)!={"path","method","body"}:
            raise DraftWriteError("INVALID_COMMAND",400)
        path,method,body=command["path"],command["method"],command["body"]
        if not isinstance(path,str) or "?" in path or not isinstance(body,dict):
            raise DraftWriteError("INVALID_COMMAND",400)
        repo=WebDraftRepository(config,test_only=test_only)
        try:
            match=ITEM.fullmatch(path)
            handoff=HANDOFF.fullmatch(path)
            preflight=PREFLIGHT.fullmatch(path)
            bootstrap=BOOTSTRAP.fullmatch(path)
            if method=="POST" and bootstrap:
                if test_only or os.environ.get("STORYOS_WEB_BOOTSTRAP_ENABLE")!="1":
                    raise BootstrapBlocked("EPISODE_BOOTSTRAP_DISABLED",403)
                auth=os.environ.get("STORYOS_WEB_BOOTSTRAP_MYSQL_AUTH","")
                if not Path(auth).is_absolute():
                    raise BootstrapBlocked("EPISODE_WRITER_NOT_CONFIGURED",503)
                writer_file=Path(auth).resolve(strict=True)
                if (writer_file.name!="bootstrap-mysql-writer.json" or writer_file.parent.name!="web-drafts"
                    or writer_file.parent.parent.name!=".storyos-tmp" or writer_file.stat().st_size>2048):
                    raise BootstrapBlocked("EPISODE_WRITER_AUTH_FORBIDDEN",403)
                writer=json.loads(writer_file.read_text(encoding="utf8"))
                if (writer.get("database")!="STORY_OS_RUNTIME" or writer.get("host")!="127.0.0.1"
                    or writer.get("port")!=3307 or not str(writer.get("user","")).startswith("webb_")
                    or not isinstance(writer.get("password"),str) or len(writer["password"])<32):
                    raise BootstrapBlocked("EPISODE_WRITER_IDENTITY_FORBIDDEN",403)
                for key,value in {"STORYOS_MYSQL_HOST":"127.0.0.1","STORYOS_MYSQL_PORT":"3307",
                                  "STORYOS_MYSQL_DB":"STORY_OS_RUNTIME","STORYOS_MYSQL_USER":writer["user"],
                                  "STORYOS_MYSQL_PWD":writer["password"],
                                  "STORYOS_EPISODE_META_STORE_MODE":"mysql"}.items():
                    os.environ[key]=value
                result={"status":201,"data":bootstrap_saved_episode(
                    repo.read(bootstrap.group(1)),body,root=Path(__file__).resolve().parents[1],
                    admitted=True,claim=repo.reserve_episode_bootstrap,finish=repo.complete_episode_bootstrap)}
            elif method=="POST" and preflight:
                result={"status":200,"data":execute_saved_dry_run(
                    repo.read(preflight.group(1)), body, root=Path(__file__).resolve().parents[1])}
            elif method=="GET" and handoff:
                result={"status":200,"data":compile_handoff_plan(repo.read(handoff.group(1)))}
            elif method=="GET" and path==BASE:
                result={"status":200,"data":repo.list()}
            elif method=="GET" and match:
                result={"status":200,"data":repo.read(match.group(1))}
            elif method=="POST" and path==BASE:
                result={"status":201,"data":repo.save(body.get("request_id"),body.get("backup"))}
            elif method=="PUT" and match:
                result={"status":200,"data":repo.save(body.get("request_id"),body.get("backup"),
                                                       match.group(1),body.get("expected_version"))}
            else:
                raise DraftWriteError("ROUTE_NOT_FOUND",404)
        finally:
            repo.close()
    except BootstrapBlocked as exc:
        result={"status":exc.status,"code":exc.code,"message":exc.code}
    except PreflightBlocked as exc:
        result={"status":exc.status,"code":exc.code,"message":exc.code}
    except DraftWriteError as exc:
        result={"status":exc.status,"code":exc.code,"message":exc.code}
    except (ValueError,TypeError,json.JSONDecodeError):
        result={"status":400,"code":"INVALID_JSON","message":"INVALID_JSON"}
    except Exception:
        result={"status":503,"code":"WEB_DRAFT_STORE_UNAVAILABLE","message":"草稿写入服务暂不可用"}
    sys.stdout.write(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n")

if __name__=="__main__":
    main()
