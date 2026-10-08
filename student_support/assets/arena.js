'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let rows = [], source = '';
  const filters = ['owasp_id','scenario_id','mode','application_outcome'];
  const percent = (n,d) => d ? (100*n/d).toFixed(1)+'%' : '—';
  const eligible = rs => rs.filter(r=>r.evaluation_valid);
  function csv(text) {
    const records=[]; let record=[],field='',quoted=false;
    for(let i=0;i<text.length;i++) {
      const c=text[i];
      if(c==='"') { if(quoted && text[i+1]==='"') {field+='"';i++;} else quoted=!quoted; }
      else if(c===',' && !quoted){record.push(field);field='';}
      else if((c==='\n'||c==='\r') && !quoted){if(c==='\r'&&text[i+1]==='\n')i++;record.push(field);if(record.some(Boolean))records.push(record);record=[];field='';}
      else field+=c;
    }
    if(quoted) throw Error('CSV contains an unclosed quote.');
    if(field||record.length){record.push(field);records.push(record);}
    const headers=records.shift(); if(!headers)throw Error('Empty CSV.');
    return records.map(values=>Object.fromEntries(headers.map((k,i)=>{
      const v=values[i]??'';
      return [k,v==='True'||v==='true'?true:v==='False'||v==='false'?false:v===''?null:
        ['latency_ms','cost_usd','request_count','reserved_cost_usd','prompt_tokens','completion_tokens','reasoning_tokens'].includes(k)?Number(v):v];
    })));
  }
  function load(data,label){
    const incoming=Array.isArray(data)?data:data.rows;
    if(!Array.isArray(incoming)||!incoming.length||incoming.length>5000)throw Error('Expected 1–5000 arena rows.');
    for(const r of incoming){
      if(!['vulnerable','hardened'].includes(r.mode)||!['adversarial','benign'].includes(r.kind)||
         !['LLM01','LLM02','LLM05','LLM06'].includes(r.owasp_id)||typeof r.evaluation_valid!=='boolean'||
         typeof r.attack_success!=='boolean'||!r.scenario_id||!r.application_outcome)throw Error('Invalid arena row contract.');
      for(const key of ['cost_usd','latency_ms','reserved_cost_usd'])if(r[key]!=null&&(!Number.isFinite(r[key])||r[key]<0))throw Error('Invalid numeric value.');
    }
    rows=incoming;source=label;
    filters.forEach(key=>{
      const select=$(key);select.replaceChildren(new Option('All',''));
      [...new Set(rows.map(r=>r[key]))].sort().forEach(v=>select.add(new Option(v,v)));
    });
    $('error').textContent='';render();
  }
  function rate(rs,key,kind){const x=eligible(rs).filter(r=>!kind||r.kind===kind);return {text:percent(x.filter(r=>r[key]).length,x.length),n:x.filter(r=>r[key]).length,d:x.length};}
  function render(){
    const rs=rows.filter(r=>filters.every(k=>!$(k).value||r[k]===$(k).value));
    const valid=eligible(rs),called=rs.filter(r=>r.model_called),lat=called.map(r=>r.latency_ms).filter(v=>v!=null).sort((a,b)=>a-b);
    const sum=k=>rs.reduce((n,r)=>n+(Number(r[k])||0),0);
    const usage=k=>{const known=called.filter(r=>r[k]!=null);return known.length?sum(k)+(known.length<called.length?' (partial)':''):'—';};
    const synthetic=rs.every(r=>r.evidence_type==='synthetic_fixture');
    const kinds=[...new Set(rs.map(r=>r.evidence_type))];
    $('evidence').textContent=kinds.length>1?'MIXED EVIDENCE — FILTER OR IMPORT ONE RUN':synthetic?'SYNTHETIC FIXTURES · NOT MODEL PERFORMANCE':'IMPORTED LIVE EVIDENCE · VERIFY PROVENANCE';
    $('loaded').textContent=source+' · '+rs.length+' / '+rows.length+' rows visible · '+(rs.length-valid.length)+' evaluation failures';
    const asr=rate(rs,'attack_success','adversarial'),benign=rate(rs,'benign_task_success','benign'),fp=rate(rs,'false_positive_block','benign');
    const cards=[['Attack success',asr.text,asr.n+' / '+asr.d+' evaluable attacks'],['Benign utility',benign.text,benign.n+' / '+benign.d+' evaluable controls'],
      ['False positive blocks',fp.text,fp.n+' / '+fp.d+' evaluable controls'],['Actual cost','$'+sum('cost_usd').toFixed(6),rs.filter(r=>r.cost_usd==null).length+' rows with unknown cost; held $'+sum('reserved_cost_usd').toFixed(6)],
      ['Canary leaks',String(rs.filter(r=>r.canary_leak).length),'Released by application'],['Unauthorized dispatches',String(rs.filter(r=>r.unauthorized_tool_executed).length),'SIMULATION ONLY · '+rs.filter(r=>r.unauthorized_tool_requested).length+' requested'],
      ['Unsafe output accepted',String(rs.filter(r=>r.unsafe_output_accepted).length),rs.filter(r=>r.unsafe_output_blocked).length+' blocked by application'],
      ['Latency P50 / P95',lat.length?(lat[Math.ceil(lat.length*.5)-1]/1000).toFixed(1)+' / '+(lat[Math.ceil(lat.length*.95)-1]/1000).toFixed(1)+'s':'—',sum('request_count')+' requests · '+rs.filter(r=>r.output_truncated).length+' truncated']];
    $('metrics').replaceChildren(...cards.map(([name,value,note])=>{const d=document.createElement('div');d.className='metric';const s=document.createElement('span'),b=document.createElement('strong'),n=document.createElement('small');s.textContent=name;b.textContent=value;n.textContent=note;d.append(s,b,n);return d;}));
    $('model-count').textContent=rs.filter(r=>r.model_refusal).length+' model refusals';
    $('app-count').textContent=rs.filter(r=>r.locally_blocked).length+' application blocks';
    $('technical').textContent=rs.filter(r=>r.schema_valid===false).length+' invalid JSON/schema · '+rs.filter(r=>r.transport_error).length+' transport errors · '+usage('prompt_tokens')+' input / '+usage('completion_tokens')+' output / '+usage('reasoning_tokens')+' reported reasoning tokens. Missing usage is not an observed zero.';
    $('pairs').replaceChildren(...['vulnerable','hardened'].map(mode=>{const sub=rs.filter(r=>r.mode===mode),d=document.createElement('article');d.className='card';const h=document.createElement('h3');h.textContent=mode.toUpperCase();d.append(h);['LLM01','LLM02','LLM05','LLM06'].forEach(f=>{const p=document.createElement('p'),q=rate(sub.filter(r=>r.owasp_id===f),'attack_success','adversarial');p.textContent=f+' · ASR '+q.text+' ('+q.n+'/'+q.d+')';d.append(p);});return d;}));
    $('rows').replaceChildren(...rs.map(r=>{const tr=document.createElement('tr');
      [r.scenario_id,r.mode,r.application_outcome,r.attack_success?'Yes':'No',r.model_refusal?'Refused':r.model_decision||'No inference',r.control||'—',r.cost_usd==null?'Unknown':'$'+r.cost_usd.toFixed(6)].forEach((v,i)=>{const td=document.createElement('td');if(i===2){const span=document.createElement('span');span.className='outcome-pill'+(r.attack_success?' attack':r.locally_blocked?' block':'');span.textContent=v;td.append(span);}else td.textContent=v;tr.append(td);});return tr;}));
  }
  filters.forEach(k=>$(k).addEventListener('change',render));
  $('import').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>8e6)throw Error('File exceeds 8 MB.');const text=await file.text();load(file.name.endsWith('.csv')?csv(text):JSON.parse(text),file.name);}catch(error){$('error').textContent=error.message;}});
  $('demo').addEventListener('click',()=>load(window.ARENA_DEMO,'Bundled deterministic demonstration'));
  $('reset').addEventListener('click',()=>{filters.forEach(k=>$(k).value='');render();});
  load(window.ARENA_DEMO,'Bundled deterministic demonstration');
})();
