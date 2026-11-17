import {api} from './client.js';
export const datasets={
 list:()=>api('/datasets'),
 get:id=>api('/datasets/'+id),
 create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)}),
 migration:()=>api('/datasets/migration/status'),
 startMigration:()=>api('/datasets/migration/start',{method:'POST'}),
 pauseMigration:()=>api('/datasets/migration/pause',{method:'POST'}),
 resumeMigration:()=>api('/datasets/migration/resume',{method:'POST'}),
 retryMigration:()=>api('/datasets/migration/retry',{method:'POST'})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
