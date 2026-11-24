from html import escape
from uuid import UUID


def render_chat_widget(website_id: UUID, website_name: str) -> str:
    """Build the self-contained chat widget embedded in published websites."""
    template = r"""<style>
#sf-chat-button{position:fixed;right:24px;bottom:24px;z-index:2147483000;border:0;border-radius:999px;background:#111827;color:#fff;padding:14px 20px;font:600 15px system-ui;box-shadow:0 8px 24px #0003;cursor:pointer}
#sf-chat-box{display:none;position:fixed;right:24px;bottom:84px;z-index:2147483000;width:min(360px,calc(100vw - 32px));height:480px;background:white;border:1px solid #ddd;border-radius:16px;box-shadow:0 12px 36px #0003;font:14px system-ui;overflow:hidden}
#sf-chat-head{background:#111827;color:#fff;padding:14px;font-weight:700}
#sf-chat-log{height:320px;overflow:auto;padding:12px;color:#222;background:#f8fafc}
.sf-chat-message{max-width:88%;margin:8px 0;padding:9px 11px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}
.sf-chat-visitor{margin-left:auto;background:#dbeafe}
.sf-chat-assistant{margin-right:auto;background:white;border:1px solid #e2e8f0}
#sf-chat-form{padding:10px;display:grid;grid-template-columns:1fr auto;gap:8px}
#sf-chat-form input,#sf-chat-form textarea{box-sizing:border-box;width:100%;padding:9px;border:1px solid #ddd;border-radius:8px;font:14px system-ui}
#sf-chat-form input{grid-column:span 2}
#sf-chat-form textarea{resize:none;height:42px}
#sf-chat-form button{background:#111827;color:white;border:0;border-radius:8px;padding:10px 14px;cursor:pointer}
#sf-chat-form button:disabled{opacity:.6;cursor:wait}
</style>
<button id="sf-chat-button" type="button">Chat with us</button>
<section id="sf-chat-box" aria-label="Chat with the store">
  <header id="sf-chat-head">Message __NAME__</header>
  <div id="sf-chat-log" aria-live="polite"><div class="sf-chat-message sf-chat-assistant">Hi! Ask us anything about __NAME__.</div></div>
  <form id="sf-chat-form">
    <input name="name" placeholder="Your name" maxlength="160">
    <input name="email" type="email" placeholder="Your email (optional)" maxlength="255">
    <textarea name="message" placeholder="Write your message" required maxlength="5000"></textarea>
    <button>Send</button>
  </form>
</section>
<script>
(()=>{
  const button=document.getElementById('sf-chat-button');
  const box=document.getElementById('sf-chat-box');
  const form=document.getElementById('sf-chat-form');
  const log=document.getElementById('sf-chat-log');
  const submit=form.querySelector('button');
  const siteId='__ID__';
  let conversationId=localStorage.getItem('sf-chat-'+siteId)||crypto.randomUUID();
  let loaded=false;
  localStorage.setItem('sf-chat-'+siteId,conversationId);
  const addMessage=(text,type)=>{
    const item=document.createElement('div');
    item.className='sf-chat-message sf-chat-'+type;
    item.textContent=text;
    log.appendChild(item);
    log.scrollTop=log.scrollHeight;
    return item;
  };
  button.onclick=async()=>{
    box.style.display=box.style.display==='block'?'none':'block';
    if(loaded)return;
    loaded=true;
    try{
      const response=await fetch('/v1/api/website-builder/public/sites/'+siteId+'/messages/'+encodeURIComponent(conversationId));
      if(!response.ok)return;
      const history=await response.json();
      if(history.length){
        log.replaceChildren();
        history.forEach(message=>addMessage(message.message,message.sender_type==='visitor'?'visitor':'assistant'));
      }
    }catch{}
  };
  form.onsubmit=async event=>{
    event.preventDefault();
    const data=new FormData(form);
    const message=String(data.get('message')||'').trim();
    if(!message)return;
    addMessage(message,'visitor');
    form.elements.message.value='';
    submit.disabled=true;
    const pending=addMessage('Typing…','assistant');
    try{
      const response=await fetch('/v1/api/website-builder/public/sites/'+siteId+'/messages',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({conversation_id:conversationId,sender_name:data.get('name')||null,sender_email:data.get('email')||null,message})
      });
      if(!response.ok)throw new Error('Message send failed');
      const result=await response.json();
      pending.textContent=result.reply||'Thanks for your message. The store will follow up soon.';
    }catch{
      pending.textContent='Sorry, your message could not be sent. Please try again.';
      form.elements.message.value=message;
    }finally{
      submit.disabled=false;
    }
  };
})();
</script>"""
    return template.replace("__NAME__", escape(website_name)).replace("__ID__", str(website_id))
