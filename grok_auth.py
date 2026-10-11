"""Official Grok CLI device authorization through the native gateway."""
import urllib.parse
from backend import AccountError
from chatgpt_auth import ChatGPTAuth

class GrokAuth(ChatGPTAuth):
    def accounts(self):
        return [a for a in self.controller.request('/auth-files').get('files',[])
                if a.get('provider',a.get('type'))=='xai' and not a.get('runtime_only') and a.get('source') != 'memory']

    def begin_login(self):
        result=self.controller.request('/xai-auth-url?is_webui=true')
        parts=urllib.parse.urlsplit(result.get('url',''))
        if parts.scheme!='https' or parts.hostname not in ('accounts.x.ai','auth.x.ai') or not result.get('state'):
            raise AccountError('The gateway did not provide a safe Grok sign-in page.')
        return result

    def quota(self, account):
        # Grok CLI provides access/cooldowns with requests, not ChatGPT's 5h/1w usage API.
        return {'windows':[], 'plan_type':account.get('plan_type') or 'Plan unknown'}

    def start_full_quota_window(self, account, quota, now=None):
        return None
