/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string,unit:string,unit_label:string,research_unit_label:string,migration_status:string,conversion:Object}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,unit_basis:Object}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,version:number,status:string,paused:boolean,note:string,report:Object}} MigrationRun */
/** @typedef {{id:number,dataset_id:number,dataset:string,status:string,unit_from:string,unit_to:string,before_totals:Object,after_totals:Object,samples:Array,reason:string,attempts:number,arrived_during_migration:boolean}}} MigrationItem */
export {};
