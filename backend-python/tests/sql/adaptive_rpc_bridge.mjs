// Test-only in-process PostgreSQL bridge. No URLs, credentials or network.
import fs from 'node:fs/promises';
import readline from 'node:readline';
const {PGlite}=await import(process.env.PLANNING_SQL_TEST_MODULE || '@electric-sql/pglite');
const db=new PGlite();
await db.exec('create role anon; create role authenticated; create role service_role bypassrls; create schema auth; create table auth.users(id uuid primary key);');
await db.exec("insert into auth.users values ('11111111-1111-4111-8111-111111111111'),('22222222-2222-4222-8222-222222222222');");
await db.exec(await fs.readFile(new URL('../../migrations/005_adaptive_section_checkpoints_REVIEW_ONLY.sql',import.meta.url),'utf8'));
await db.exec('select public.adaptive_purge_expired();set role service_role;');
console.log(JSON.stringify({ready:true}));
for await(const line of readline.createInterface({input:process.stdin,crlfDelay:Infinity})){
 try{
  const {query,values}=JSON.parse(line);
  if(!/^SELECT row_to_json\(q\)::text FROM public\.adaptive_[a-z_]+\(/.test(query))throw Error('Unexpected test query');
  let i=0;const sql=query.replaceAll('%s',()=>'$'+(++i));
  const result=await db.query(sql,values);
  console.log(JSON.stringify({rows:result.rows.map(row=>JSON.parse(row.row_to_json))}));
 }catch(error){console.log(JSON.stringify({error:error.message,code:error.code}));}
}
await db.close();
