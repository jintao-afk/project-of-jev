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
const requests=[],paths=[],checks=[];
const saved=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/ui-responses.json'),'utf8'));
const agentSaved=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/agent-responses.json'),'utf8'));
const r1Saved=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/r1-responses.json'),'utf8'));
const calc=saved.calc;
const report=id=>saved.cases[id];
let fixture=calc,failHttp=false,copied='';
const context=vm.createContext({
  document:{getElementById:id=>{assert(nodes[id],`unknown id ${id}`);return nodes[id];},
            createElement:tag=>new NodeDouble(tag),createElementNS:(ns,tag)=>new NodeDouble(tag),
            querySelectorAll:selector=>selector==='[data-example]'?examples:selector==='[data-tab]'?tabs:[]},
  performance:{now:()=>1000},navigator:{clipboard:{writeText:async text=>{copied=text;}}},
  setInterval:()=>1,clearInterval(){},setTimeout:()=>2,clearTimeout(){},URL,console,
  fetch:async(url,options)=>{
    paths.push(url);
    if(url==='/v1/status')return{ok:true,json:async()=>({version:'0.6.0',decision_model:'Qwen/Qwen3-1.7B',decision_model_ready:true,retrieval_model_ready:true,offline_mode:true})};
    if(url==='/v1/tasks')return{ok:true,json:async()=>({tasks:[{task_id:r1Saved.waiting.task_id,revision:r1Saved.waiting.revision,goal:r1Saved.waiting.goal,status:r1Saved.waiting.status,resumable:r1Saved.waiting.resumable}]})};
    if(url==='/v1/tasks/'+r1Saved.waiting.task_id&&!options)return{ok:true,json:async()=>r1Saved.waiting};
    assert(url==='/v1/run'||url==='/v1/tasks/'+r1Saved.waiting.task_id+'/continue','unexpected POST route '+url);
    assert.equal(options.method,'POST');requests.push(JSON.parse(options.body));
    return{ok:!failHttp,json:async()=>failHttp?{error:'已有处理正在运行'}:fixture};
  }
});
vm.runInContext(script,context);
function check(name,fn){fn();checks.push({name,status:'passed'});}
async function submit(){await nodes['task-form'].requestSubmit();}
function descendants(node){return[node,...node.children.flatMap(child=>typeof child==='string'?[]:descendants(child))];}
function displayedLinks(){return descendants(nodes.result).filter(node=>node.tag==='a');}
async function settle(){await new Promise(resolve=>setImmediate(resolve));}
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
  fixture=saved.iteration.c01;await submit();
  check('Task contract lists fields without claiming semantic completion',()=>{assert(nodes.result.textContent.includes('原因'));assert(nodes.result.textContent.includes('地点'));assert(nodes.result.textContent.includes('检查通过不代表语义正确'));assert.equal(nodes['status-label'].textContent,'已返回 · 待检查');});
  fixture=saved.iteration.c11;await submit();
  check('Contract preflight requests source without a fabricated model decision',()=>{assert.equal(nodes['status-label'].textContent,'待补充原文');assert.equal(nodes['metric-calls'].textContent,'0');assert(nodes.routing.textContent.includes('未得到有效选择'));});
  await nodes['workflow-example'].fire('click');
  check('Workflow example declares directory, fields and bounds',()=>{assert.equal(nodes['task-mode'].value,'workflow');assert(!nodes['workflow-options'].hidden);assert(nodes['material-field'].hidden);assert.equal(nodes['workflow-threshold'].value,'2000');});
  fixture=saved.workflow;await submit();
  check('Workflow sends structured offline contract',()=>{const body=requests.at(-1);assert.equal(body.mode,'workflow');assert.equal(body.workflow.input_dir,'demo');assert.equal(body.workflow.threshold,'2000');assert.equal(body.allow_remote,false);});
  check('Actual multi-step response exposes only local report links and scoped validation',()=>{assert(nodes.result.textContent.includes('下载分析报告'));assert(nodes.result.textContent.includes('baseline.csv'));assert(nodes['summary'].textContent.includes('声明'));assert.equal(nodes['metric-calls'].textContent,'11');assert(!nodes['task-mode'].disabled);});
  const links=nodes.result.children.find(n=>n.className==='artifact-links');
  check('Report links restrict artifacts to UUID-local routes',()=>assert(links.children.every(a=>/^\/v1\/artifacts\/[a-f0-9]{32}\/report\.(md|json)$/.test(a.href))));
  await examples.find(n=>n.dataset.example==='calc').fire('click');
  check('Single task example restores the original material form',()=>{assert.equal(nodes['task-mode'].value,'single');assert(nodes['workflow-options'].hidden);assert(!nodes['material-field'].hidden);});
  await nodes['agent-example'].fire('click');
  check('General agent example gives explicit numbered tasks and locks offline selector',()=>{assert.equal(nodes['task-mode'].value,'agent');assert(nodes.goal.value.includes('1. 计算'));assert(nodes.goal.value.includes('2. 计算'));assert(nodes.backend.disabled);});
  fixture=agentSaved.arithmetic;await submit();
  check('General agent request uses real AnyJev and preserves all user tasks',()=>{assert.equal(requests.at(-1).mode,'agent');assert.equal(requests.at(-1).backend,'anyjev');assert(nodes.result.textContent.includes('用户任务清单'));assert(nodes.result.textContent.includes('(18+24)/6'));assert(nodes.result.textContent.includes('(9+15)*2'));assert(nodes.result.textContent.includes('48'));assert(nodes['summary'].textContent.includes('仍待核查'));});
  fixture=agentSaved['summary-chain'];await submit();
  await nodes['tab-decision'].fire('click');
  check('General agent displays actual source choices and distinct raw and final service selections',()=>{assert(nodes.routing.textContent.includes('AnyJev 选择资料来源：$s1'));assert(nodes.routing.textContent.includes('最终选择（含程序约束）'));assert(nodes.routing.textContent.includes('原始选择'));assert(nodes.routing.textContent.includes('非正确率'));assert(nodes.result.textContent.includes('70'));});
  fixture=agentSaved['retrieval-chain'];await submit();
  check('Source constraint is displayed as a program adjustment rather than model review',()=>{assert(nodes.routing.textContent.includes('程序调整'));assert(nodes.result.textContent.includes('总结上一步检索结果'));});
  fixture=agentSaved.unsupported;await submit();
  check('General agent blocked operation shows a real stop and no fake actuation',()=>{assert.equal(nodes['status-label'].textContent,'已停止');assert.equal(nodes['metric-calls'].textContent,'0');assert(nodes.result.textContent.includes('未执行设备或联网操作'));});
  // R1 interaction replay: all task results below come from saved real HTTP responses.
  // Assertions cover request binding and presentation, not independent semantic accuracy.
  await nodes['r1-dataset-example'].fire('click');
  check('R1 dataset example enables attachment and preserves explicit comparison order',()=>{assert.equal(nodes['task-mode'].value,'agent');assert(nodes['agent-dataset'].checked);assert(!nodes['workflow-options'].hidden);assert.equal(nodes['workflow-dir'].value,'r1-demo');assert.equal(nodes['workflow-value'].value,'latency_ms');assert.equal(nodes['workflow-files'].value,'baseline.csv, current.csv');assert.equal(nodes['workflow-threshold'].value,'200');});
  fixture=r1Saved.dataset;await submit();
  check('R1 unified request binds CSV contract and stays offline',()=>{const body=requests.at(-1);assert.equal(body.mode,'agent');assert.equal(body.backend,'anyjev');assert.deepEqual(body.dataset.files,['baseline.csv','current.csv']);assert.equal(body.dataset.input_dir,'r1-demo');assert.equal(body.dataset.value_column,'latency_ms');assert.equal(body.dataset.threshold,'200');assert.equal(body.dataset.include_suggestions,false);assert(!Object.hasOwn(body,'workflow'));assert.equal(body.allow_remote,false);assert.equal(body.network_available,false);assert.equal(body.goal,r1Saved.dataset.goal);});
  check('R1 delivery exposes parent and child report links while retaining review status',()=>{const expected=[...r1Saved.dataset.artifacts,...Object.values(r1Saved.dataset.subtask_results).flatMap(value=>value.result?.artifacts||[])];const shown=displayedLinks();assert(expected.length>=4);for(const file of expected)assert(shown.some(link=>link.href===file.url));assert(shown.every(link=>/^\/v1\/artifacts\/[a-f0-9]{32}\/report\.(md|json)$/.test(link.href)));assert(nodes.result.textContent.includes('CSV成果'));assert.equal(nodes['status-label'].textContent,'已交付 · 待核查');assert(nodes['summary'].textContent.includes('正确性仍待核查'));assert(nodes['continue-box'].hidden);});
  await nodes['r1-continue-example'].fire('click');fixture=r1Saved.waiting;await submit();
  check('R1 waiting task retains completed work, pending requirement and stage download',()=>{assert.equal(nodes['status-label'].textContent,'待补充资料');assert(!nodes['continue-box'].hidden);assert(nodes['summary'].textContent.includes('已完成步骤将保留'));assert(nodes.result.textContent.includes('待执行'));assert(nodes.result.textContent.includes(r1Saved.waiting.pending_subtasks[0].goal));for(const file of r1Saved.waiting.artifacts)assert(displayedLinks().some(link=>link.href===file.url));assert.equal(JSON.parse(nodes.full.textContent).execution_complete,false);});
  const beforeEmptySupplement=requests.length;nodes['continue-input'].value='  ';nodes['continue-dataset'].checked=false;await nodes['continue-run'].fire('click');
  check('R1 empty supplement never sends a continuation request',()=>{assert.equal(requests.length,beforeEmptySupplement);assert(!nodes['continue-error'].hidden);assert(nodes['continue-error'].textContent.includes('补充原文'));});
  const supplement='The delivery date has not been confirmed.';nodes['continue-input'].value=supplement;fixture=r1Saved.resumed;await nodes['continue-run'].fire('click');
  check('R1 continuation posts only new input to the saved task URL',()=>{assert.equal(paths.filter(url=>url.endsWith('/continue')).at(-1),'/v1/tasks/'+r1Saved.waiting.task_id+'/continue');assert.deepEqual(requests.at(-1),{input:supplement});assert.equal(JSON.parse(nodes.full.textContent).task_id,r1Saved.waiting.task_id);assert.equal(JSON.parse(nodes.full.textContent).revision,2);assert.equal(nodes['status-label'].textContent,'已交付 · 待核查');assert(nodes['continue-box'].hidden);});
  check('R1 resumed delivery keeps previous-stage links distinct from current downloads',()=>{const shown=displayedLinks();for(const file of r1Saved.resumed.artifacts)assert(shown.some(link=>link.href===file.url));for(const stage of r1Saved.resumed.previous_stages)for(const file of stage.artifacts)assert(shown.some(link=>link.href===file.url&&link.textContent.includes('此前阶段 '+stage.revision)));assert(nodes.result.textContent.includes('阶段 2'));});
  const beforeHistory=requests.length;await nodes['history-refresh'].fire('click');await settle();const historyButton=nodes['task-history'].children.find(node=>node.dataset?.taskId===r1Saved.waiting.task_id);assert(historyButton);await historyButton.fire('click');await settle();
  check('R1 saved history reloads by GET and locks the resumable goal',()=>{assert.equal(requests.length,beforeHistory);assert(paths.includes('/v1/tasks'));assert(paths.includes('/v1/tasks/'+r1Saved.waiting.task_id));assert.equal(nodes.goal.value,r1Saved.waiting.goal);assert.equal(nodes.goal.readOnly,true);assert.equal(nodes['status-label'].textContent,'待补充资料');assert(!nodes['continue-box'].hidden);assert.equal(nodes['input'].value,'');});
  await nodes['r1-continue-example'].fire('click');
  check('R1 new-task example restores goal editing and clears inherited CSV binding',()=>{assert.equal(nodes.goal.readOnly,false);assert.equal(nodes['agent-dataset'].checked,false);assert(nodes['workflow-options'].hidden);assert.equal(nodes['task-mode'].value,'agent');assert.equal(nodes.params.value,'{}');assert.equal(nodes.validation.value,'{}');});
  await examples.find(n=>n.dataset.example==='calc').fire('click');fixture=calc;
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
