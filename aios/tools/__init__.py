import importlib as _il
for _m in ["aios.tools.calculator","aios.tools.web_search","aios.tools.send_email","aios.tools.read_file","aios.tools.current_datetime","aios.tools.http_get","aios.tools.http_request","aios.tools.code","aios.tools.transform","aios.tools.if_branch","aios.tools.wait","aios.tools.hubspot","aios.tools.pipedrive","aios.tools.rdstation","aios.tools.python_sandbox","aios.tools.sql_query","aios.tools.crm","aios.tools.lead_scoring","aios.tools.dynamic"]:
    try:
        _il.import_module(_m)
    except Exception:
        pass
