function updateDetailLinks(c,n){
  window._curCode=c;window._curName=n;
  var old=document.getElementById('d-edinet-section');
  if(old)old.remove();
  var s=document.createElement('div');
  s.id='d-edinet-section';s.className='rb';s.style.marginTop='8px';
  var eu='https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?S1='+c;
  var ku='https://kabutan.jp/stock/?code='+c;
  s.innerHTML=
    '<div class="rb-t" style="color:#475569;">External Links</div>'
    +'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">'
    +'<a href="'+eu+'" target="_blank" style="display:inline-flex;align-items:center;gap:5px;padding:5px 12px;background:#1e2d40;border:1px solid #3b82f6;border-radius:5px;color:#60a5fa;font-size:10px;font-weight:700;text-decoration:none;">EDINET</a>'
    +'<a href="'+ku+'" target="_blank" style="display:inline-flex;align-items:center;gap:5px;padding:5px 12px;background:#1e2d40;border:1px solid #374151;border-radius:5px;color:#94a3b8;font-size:10px;font-weight:700;text-decoration:none;">Kabutan</a>'
    +'</div>'
    +'<div style="margin-top:12px;border:1px solid #f59e0b;border-radius:8px;overflow:hidden;">'
    +'<div style="background:#1c1400;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;">'
    +'<span style="color:#f59e0b;font-weight:800;font-size:11px;">Deep Insight Analysis</span>'
    +'<button onclick="runKenja()" style="background:#f59e0b;color:#0d1117;border:none;border-radius:4px;padding:4px 12px;font-size:10px;font-weight:800;cursor:pointer;">Analyze</button>'
    +'</div>'
    +'<div id="kenja-result" style="padding:10px 12px;min-height:40px;background:#0d1117;color:#94a3b8;font-size:9px;">'
    +'Click Analyze to start AI analysis.'
    +'</div></div>';
  var dc=document.getElementById('d-content');
  if(dc)dc.appendChild(s);
}

function kenjaPrompt(){
  return 'You are a professional securities analyst. Analyze the financial reports of '
    +window._curName+' (code: '+window._curCode+') based on public information.

'
    +'Output in Japanese with this format:

'
    +'[Part A] Visual Dashboard
'
    +'1.Business Results: revenue/profit change rate and reasons
'
    +'2.Growth Quality: operating margin change and reasons
'
    +'3.Sustainability: structural vs one-time factors
'
    +'4.Outlook: official forecasts, management tone
'
    +'5.Risks: high/medium/low level items
'
    +'6.Cash Flow: operating/investing/free CF
'
    +'7.Final Verdict: credibility level and 3 reasons

'
    +'[Part B] Detailed Report (3-5 sentences each)
'
    +'Overview/Growth/Sustainability/Future/Risks/CF/Conclusion';
}

function runKenja(){
  var code=window._curCode,name=window._curName;
  if(!code)return;
  var res=document.getElementById('kenja-result');
  if(!res)return;
  res.innerHTML='<div style="color:#f59e0b;text-align:center;padding:20px;">Analyzing... (30-60sec)<br>'
    +'<div style="font-size:8px;color:#475569;margin-top:6px;">'+name+' ('+code+')</div></div>';
  fetch('https://api.anthropic.com/v1/messages',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      model:'claude-sonnet-4-20250514',
      max_tokens:3000,
      messages:[{role:'user',content:[{type:'text',text:kenjaPrompt()}]}]
    })
  }).then(function(r){return r.json();}).then(function(api){
    if(api.error)throw new Error(api.error.message||'API error');
    var txt=api.content&&api.content[0]?api.content[0].text:'error';
    var pA=txt.split('[Part B]')[0]||txt;
    var pB=txt.split('[Part B]')[1]||'';
    res.innerHTML='<div style="color:#e2e8f0;font-size:9px;line-height:1.7;white-space:pre-wrap;border-bottom:1px solid #374151;padding-bottom:10px;margin-bottom:8px;">'+escH(pA)+'</div>'
      +(pB?'<details open><summary style="color:#f59e0b;cursor:pointer;font-size:10px;font-weight:700;padding:4px 0;">Detailed Report (Part B)</summary><div style="color:#cbd5e1;font-size:9px;line-height:1.7;white-space:pre-wrap;margin-top:6px;">'+escH('[Part B]'+pB)+'</div></details>':'');
  }).catch(function(e){
    res.innerHTML='<div style="color:#f87171;padding:10px;">Error: '+e.message+'<br>'
      +'<a href="https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?S1='+code+'" target="_blank" style="color:#60a5fa;font-size:9px;">Open EDINET</a></div>';
  });
}

function escH(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
