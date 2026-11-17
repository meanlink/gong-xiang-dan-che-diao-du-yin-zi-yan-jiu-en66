import {datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify,fmt,date} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

const MIGRATION_LABEL={pending:'待迁移',processing:'迁移中',converted:'已换算',failed:'失败',abandoned:'已放弃'};
const RUN_LABEL={running:'迁移进行中',paused:'已暂停',completed:'核对完成',superseded:'被新轮接管',pending:'待开始'};

function unitOptions(m){
  return (m.unit_options||[{value:'',label:'未声明（按人数）'}]).map(o=>'<option value="'+esc(o.value)+'" '+(o.value==='count_per_half_hour'?'selected':'')+'>'+esc(o.label)+'</option>').join('');
}

function conversionRows(item){
  const cols=[{key:'field',label:'字段'},{key:'before',label:'换算前合计'},{key:'after',label:'换算后合计'}];
  const names={arrivals:'附近到达客流',demand:'借车需求'};
  const rows=Object.keys(names).filter(k=>item.before_totals[k]!==undefined).map(k=>({field:names[k],before:fmt(item.before_totals[k]),after:fmt(item.after_totals[k])}));
  return table(cols,rows);
}

function sampleRows(item){
  const rows=(item.samples||[]).map(s=>({station:s.station,period:s.period,
    arrivals_before:fmt(s.before?.arrivals),arrivals_after:fmt(s.after?.arrivals),
    demand_before:fmt(s.before?.demand),demand_after:fmt(s.after?.demand)}));
  return table([{key:'station',label:'站点'},{key:'period',label:'时段'},{key:'arrivals_before',label:'客流原值'},{key:'arrivals_after',label:'客流人数'},{key:'demand_before',label:'借车原值'},{key:'demand_after',label:'借车人数'}],rows);
}

function migrationPanel(s,m){
  const run=s.run,counts=s.counts;
  const canOperate=session.user.role==='admin';
  const state=run?RUN_LABEL[run.status]||run.status:'尚未开始单位迁移';
  const converted=s.items.filter(i=>i.status==='converted');
  const waiting=s.items.filter(i=>i.status!=='converted');
  const button=(id,label,enabled)=>'<button type="button" class="button small" id="'+id+'" '+(canOperate&&enabled?'':'disabled')+'>'+label+'</button>';
  return '<section class="panel migration-panel"><div class="section-title"><h2>单位迁移 · 核对台</h2><span>'+esc(state)+(run?' · 第 '+run.version+' 轮':'')+'</span></div>'+
    '<p class="hint">旧批次按原值逐批换算为人数，原值不覆盖；接报与分析不等迁移。暂停后已完成批次不重做，重试始终从原值换算。全部历史批次与迁移期间新增批次核实后才报完成。</p>'+
    '<div class="migration-stats">'+
      [['批次',counts.total],['已换算',counts.converted],['待迁',counts.pending],['失败',counts.failed],['迁移期间新增',counts.arrived]].
        map(([k,v])=>'<div><span>'+k+'</span><strong>'+v+'</strong></div>').join('')+'</div>'+
    (run?'<p class="migration-note">'+esc(run.note||'')+(run.report&&run.report.finished_at?' · 完成于 '+date(run.report.finished_at):'')+'</p>':'')+
    '<div class="migration-actions">'+button('migration-start','开始 / 接管迁移',run?.status!=='running')+button('migration-pause','暂停',run?.status==='running')+button('migration-resume','继续',run?.status==='paused')+button('migration-retry','重试失败批次',(run?.status==='paused'||run?.status==='completed')&&counts.failed>0)+'<button type="button" class="button small" id="migration-refresh">刷新核对台 ↻</button></div>'+
    (counts.failed? '<div class="section-title"><h3>缺项与失败原因</h3><span>已完成核对 · 缺项需重试或修正原值</span></div><ul class="migration-missing">'+s.missing.map(x=>'<li><strong>'+esc(x.dataset)+'</strong> · '+esc(MIGRATION_LABEL[x.status]||x.status)+' · '+esc(x.reason||'换算未完成')+'</li>').join('')+'</ul>':'')+
    (s.pending_datasets.length? '<div class="section-title"><h3>待迁移批次</h3><span>'+esc(run?'排队中':'尚未开始')+'</span></div><ul class="migration-list">'+s.pending_datasets.map(d=>'<li><strong>'+esc(d.name)+'</strong> · '+d.rows+' 条 · '+esc(d.unit_label||'未声明（按人数）')+'</li>').join('')+'</ul>':'')+
    '<div class="section-title"><h3>已完成批次 · 换算前后</h3><span>'+converted.length+' 批</span></div>'+
    (converted.length? '<div class="migration-detail">'+converted.map(item=>'<article><header><strong>'+esc(item.dataset)+'</strong><span>'+esc(item.unit_from?item.unit_from_label:'未声明（按人数）')+' → '+esc(item.unit_to_label)+(item.arrived_during_migration?' · 迁移期间新增':'')+'</span></header>'+conversionRows(item)+'<details><summary>抽样对照</summary>'+sampleRows(item)+'</details></article>').join('')+'</div>':'<p class="empty">还没有完成换算的批次。</p>')+
    (waiting.length? '<div class="section-title"><h3>未完成批次</h3><span>'+waiting.length+' 批</span></div><div class="migration-detail">'+waiting.map(item=>'<article><header><strong>'+esc(item.dataset)+'</strong><span>'+esc(MIGRATION_LABEL[item.status]||item.status)+' · 第 '+item.attempts+' 次</span></header><p class="hint">'+esc(item.reason||'等待迁移')+'</p></article>').join('')+'</div>':'')+
    (s.runs.filter(r=>r.status==='superseded').length? '<p class="hint">历史轮次：'+s.runs.filter(r=>r.status==='superseded').map(r=>'第 '+r.version+' 轮 · '+esc(r.note)).join('；')+'</p>':'')+
    '</section>';
}

export async function dataPage(){
 workspace.datasets=await datasets.list();const migration=await datasets.migration();workspace.migration=migration;
 let selected=workspace.datasets[0]?await datasets.get(workspace.datasets[0].id):null,m=workspace.meta;
 const selectedNote=selected?'<p class="hint">声明单位：'+esc(selected.unit_label||'未声明（按人数）')+' · 研究口径：'+esc(selected.research_unit_label)+' · 换算系数 '+selected.conversion.factor+'</p>':'';
 return heading('02 / DATA INTAKE','数据接入与批次追溯','保留供稿方原值与单位声明，统一换算为人数研究；未知单位拒收，旧批次可逐批在线迁移。')+'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div><div class="batch-list">'+workspace.datasets.map(d=>'<button class="batch-item" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+d.rows+' 条 · '+esc(d.source)+' · '+esc(d.unit_label||'未声明（按人数）')+'</span><small>SHA256 '+esc(d.checksum.slice(0,18))+'… · '+esc(d.migration_status||'待迁移')+'</small></button>').join('')+'</div><div class="section-title"><h2>接入新数据</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>供稿单位<select name="unit">'+unitOptions(m)+'</select></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><p class="hint">字段：'+m.columns.map(c=>esc(c.key)+' / '+esc(c.label)).join('，')+'。5–5,000 条记录。'+(m.unit_note?esc(m.unit_note):'')+'</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并接入批次</button></form></section><section class="panel"><div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span>预览前 30 条（研究人数）</span></div>'+selectedNote+'<div id="data-preview">'+table(m.columns,selected?.research_records||[])+'</div>'+(selected?'<details class="raw-detail"><summary>查看供稿方原值</summary>'+table(m.columns,selected.records.slice(0,30))+'</details>':'')+'</section></div>'+migrationPanel(migration,m);
}

export function bindData(refresh){
 let source='manual.json';
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{try{const d=await datasets.get(button.dataset.dataset);document.querySelector('#preview-name').textContent=d.name;document.querySelector('#data-preview').innerHTML=table(workspace.meta.columns,d.research_records);}catch(error){notify(error.message,true);}});
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,unit:f.get('unit'),records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});
 const actions={start:['startMigration','已开始迁移，worker 将逐批换算'],pause:['pauseMigration','迁移已暂停，已完成批次保留'],resume:['resumeMigration','迁移继续，跳过已完成批次'],retry:['retryMigration','失败批次已重新排队']};
 document.querySelector('#migration-refresh').onclick=()=>refresh();
 for(const [key,[method,message]] of Object.entries(actions)){
   const button=document.querySelector('#migration-'+key);
   if(!button)continue;
   button.onclick=async()=>{button.disabled=true;try{await datasets[method]();notify(message);await refresh();}catch(error){notify(error.message,true);button.disabled=false;}};
 }
}
