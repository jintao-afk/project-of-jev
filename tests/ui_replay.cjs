// Frontend-only replay using saved real responses and a minimal DOM double.
// No browser, HTTP navigation, model inference or screenshot is performed.
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'ui.html'),'utf8');
const markup=html.split('<script>')[0];
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const ids=[...markup.matchAll(/\sid="([^"]+)"/g)].map(m=>m[1]);
assert.equal(ids.length,new Set(ids).size,'duplicate IDs');
assert(!/<(?:script|link)\b[^>]*(?:src|href)=/i.test(markup),'external assets');
new vm.Script(script,{filename:'ui.html'});

class NodeDouble{
  constructor(tag='div'){this.tag=tag;this.children=[];this.attributes={};this.handlers={};this._text='';this.value='';this.hidden=false;this.disabled=false;this.dataset={};this.style={};this.open=false;this.className='';this.classList={toggle:(k,active)=>{const set=new Set(this.className.split(' ').filter(Boolean));if(active)set.add(k);else set.delete(k);this.className=[...set].join(' ');},remove:k=>{this.className=this.className.split(' ').filter(c=>c!==k).join(' ');}};}
  set textContent(v){this._text=String(v);this.children=[];}
  get textContent(){return this._text+this.children.map(c=>typeof c==='string'?c:c.textContent).join('');}
  append(...values){this.children.push(...values);}
  replaceChildren(...values){this._text='';this.children=values;}
  setAttribute(k,v){this.attributes[k]=String(v);}
  getAttribute(k){return this.attributes[k]??null;}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(k,fn){(this.handlers[k]??=[]).push(fn);}
  closest(){return outputPanel;}
  focus(){focused=this;}
  requestSubmit(){return Promise.all((this.handlers.submit||[]).map(fn=>fn({preventDefault(){}})));}
  async fire(k,event={}){for(const fn of this.handlers[k]||[])await fn(event);}
}
let focused=null;
const nodes=Object.fromEntries(ids.map(id=>[id,new NodeDouble()]));
const outputPanel=new NodeDouble();
nodes.params.value='{}';nodes.validation.value='{}';nodes.backend.value='anyjev';
nodes['offline-mode'].lastChild={textContent:'完全离线'};
nodes['trace-toggle'].setAttribute('aria-expanded','false');
const examples=['qa','text','calc','retrieve'].map(key=>{const n=new NodeDouble('button');n.dataset.example=key;return n;});
const tabs=['answer','decision','record'].map(key=>{nodes['tab-'+key].dataset.tab=key;return nodes['tab-'+key];});
const requests=[],checks=[];
const calc=JSON.parse(fs.readFileSync(path.join(root,'reports/ui-run-v030.json'),'utf8'));
const development=JSON.parse(fs.readFileSync(path.join(root,'logs/evaluations/dev-anyjev-frozen-dev-20261014-130616-954080.json'),'utf8'));
const report=id=>development.results.find(r=>r.case===id).report;
let fixture=calc,failHttp=false,copied='';
const context=vm.createContext({
  document:{getElementById:id=>{assert(nodes[id],`unknown id ${id}`);return nodes[id];},
            createElement:tag=>new NodeDouble(tag),createElementNS:(ns,tag)=>new NodeDouble(tag),
            querySelectorAll:selector=>selector==='[data-example]'?examples:selector==='[data-tab]'?tabs:[]},
  performance:{now:()=>1000},navigator:{clipboard:{writeText:async text=>{copied=text;}}},
  setInterval:()=>1,clearInterval(){},setTimeout:()=>2,clearTimeout(){},URL,console,
  fetch:async(url,options)=>{if(url==='/v1/status')return{ok:true,json:async()=>({version:'0.3.0',decision_model:'Qwen/Qwen3-1.7B',decision_model_ready:true,retrieval_model_ready:true,offline_mode:true})};assert.equal(url,'/v1/run');requests.push(JSON.parse(options.body));return{ok:!failHttp,json:async()=>failHttp?{error:'已有处理正在运行'}:fixture};}
});
vm.runInContext(script,context);
function check(name,fn){fn();checks.push({name,status:'passed'});}
async function submit(){await nodes['task-form'].requestSubmit();}
async function main(){
  await new Promise(resolve=>setImmediate(resolve));
  check('JavaScript syntax, unique IDs and no external assets',()=>assert(ids.length>40));
  check('Local readiness label',()=>assert.equal(nodes['connection-text'].textContent,'本地服务已连接'));
  await submit();
  check('Empty goal blocks request and focuses goal',()=>{assert.equal(requests.length,0);assert.equal(focused,nodes.goal);assert(!nodes['input-error'].hidden);});
  await examples.find(n=>n.dataset.example==='calc').fire('click');
  check('Example fills complete task and updates counter',()=>{assert(nodes.goal.value.includes('计算工具'));assert.equal(JSON.parse(nodes.validation.value).expected_value,7);assert(nodes['goal-count'].textContent.startsWith(String(nodes.goal.value.length)));});
  nodes.params.value='[1]';await submit();
  check('Invalid JSON object opens advanced settings without request',()=>{assert(nodes.advanced.open);assert.equal(focused,nodes.params);assert.equal(requests.length,0);});
  nodes.params.value='{"expression":"(18+24)/6"}';await submit();
  check('Offline request body and completed tool result',()=>{assert.equal(requests[0].allow_remote,false);assert.equal(requests[0].network_available,false);assert.equal(nodes['status-label'].textContent,'验收条件已通过');assert(nodes.result.textContent.includes('7'));assert.equal(nodes['metric-remote'].textContent,'0');});
  check('Controls and timer state restored',()=>{assert(!nodes.run.disabled);assert.equal(nodes['run-label'].textContent,'运行任务');assert(!nodes['metrics'].hidden);assert(!nodes['answer-content'].hidden);});
  await nodes['tab-decision'].fire('click');
  check('Decision tab and score disclaimer',()=>{assert(!nodes['pane-decision'].hidden);assert(nodes.routing.textContent.includes('非正确率'));assert(nodes.routing.textContent.includes('实际执行'));assert(nodes.copy.disabled);});
  await nodes['tab-decision'].fire('keydown',{key:'ArrowRight',preventDefault(){}});
  check('Keyboard tab navigation and raw record',()=>{assert(!nodes['pane-record'].hidden);assert.equal(focused,nodes['tab-record']);assert.equal(JSON.parse(nodes.full.textContent).backend,'anyjev');});
  await nodes.copy.fire('click');
  check('Copy exact record',()=>assert.equal(JSON.parse(copied).run_id,calc.run_id));
  await nodes['trace-toggle'].fire('click');
  check('Expandable trace shows real events',()=>{assert(!nodes['trace-body'].hidden);assert.equal(nodes.events.children.length,calc.events.length);});
  fixture=report('d03');await submit();
  check('Needs-review result remains separate from completed',()=>{assert.equal(nodes['status-label'].textContent,'已返回 · 待检查');assert(nodes['summary'].textContent.includes('仍需检查'));assert(!nodes.sources.hidden);assert(nodes.sources.textContent.includes('查看资料原文'));assert(nodes['quality-note'].textContent.includes('仍需复核'));});
  fixture=report('d24');await submit();
  check('Text statistics render as three values',()=>{assert(nodes.result.textContent.includes('字符数9'));assert(nodes.result.textContent.includes('非空行数2'));assert(nodes.result.textContent.includes('空白分隔词数3'));});
  fixture=report('d11');await submit();
  check('Rejected draft labeled as a guarded fallback',()=>{assert.equal(nodes['status-label'].textContent,'草稿未通过');assert(nodes['summary'].textContent.includes('保留的原文'));});
  fixture=report('d15');await submit();
  check('Missing original requests material rather than showing success',()=>{assert.equal(nodes['status-label'].textContent,'待补充原文');assert(nodes['summary'].textContent.includes('补充资料'));});
  fixture=report('d17');await submit();
  check('Stopped request uses actual reason and no fake answer',()=>{assert.equal(nodes['status-label'].textContent,'已停止');assert(nodes.result.textContent.includes('没有观察设备'));assert.equal(nodes['metric-calls'].textContent,'0');});
  fixture={...calc,result:{text:'<img src=x onerror=alert(1)>'},status:'needs_review',task_complete:false};await submit();
  check('Model text rendered literally',()=>{assert.equal(nodes.result.children[0].tag,'div');assert.equal(nodes.result.children[0].textContent,fixture.result.text);assert.equal(nodes.result.children[0].children.length,0);});
  const iteration=JSON.parse(fs.readFileSync(path.join(root,'logs/evaluations/v031-contract-20261015-121428-916789.json'),'utf8'));
  fixture=iteration.results.find(r=>r.case==='c01').report;await submit();
  check('Task contract lists fields without claiming semantic completion',()=>{assert(nodes.result.textContent.includes('原因'));assert(nodes.result.textContent.includes('地点'));assert(nodes.result.textContent.includes('检查通过不代表语义正确'));assert.equal(nodes['status-label'].textContent,'已返回 · 待检查');});
  fixture=iteration.results.find(r=>r.case==='c11').report;await submit();
  check('Contract preflight requests source without a fabricated model decision',()=>{assert.equal(nodes['status-label'].textContent,'待补充原文');assert.equal(nodes['metric-calls'].textContent,'0');assert(nodes.routing.textContent.includes('未得到有效选择'));});
  failHttp=true;await submit();
  check('HTTP error resets state and preserves error record',()=>{assert.equal(nodes['status-label'].textContent,'请求异常');assert.equal(nodes.result.textContent,'已有处理正在运行');assert(!nodes.run.disabled);assert.equal(JSON.parse(nodes.full.textContent).error,'已有处理正在运行');});
  await nodes['tab-record'].fire('click');await nodes.copy.fire('click');
  check('Error record remains copyable',()=>{assert(!nodes.copy.disabled);assert.equal(JSON.parse(copied).error,'已有处理正在运行');});
  await nodes.reset.fire('click');
  check('Clear returns to empty workspace',()=>{assert.equal(nodes.goal.value,'');assert.equal(nodes.params.value,'{}');assert(!nodes.empty.hidden);assert(nodes.metrics.hidden);assert.equal(nodes.full.textContent,'暂无运行记录');});
  const output={mode:'frontend_source_and_saved_response_replay_not_browser_test',created_at:new Date().toISOString(),checks,passed:checks.length,visual_verification:'not_completed_browser_policy_denied_localhost_access'};
  const target=path.join(root,'logs/ui-validation-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json');
  fs.writeFileSync(target,JSON.stringify(output,null,2),{flag:'wx'});
  console.log(JSON.stringify(output,null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
