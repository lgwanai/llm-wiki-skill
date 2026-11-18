import { Presentation, PresentationFile } from "@oai/artifact-tool";

const deck = Presentation.create({slideSize:{width:1280,height:720}});
const ink = "#14253C", blue = "#1768A8", pale = "#DDEFFC";
function label(s,text,x,y,w,h,opts={}) {
  const o=s.shapes.add({geometry:opts.geometry||"textbox",position:{left:x,top:y,width:w,height:h},fill:opts.fill||"none"});
  o.text=text;
  o.text.style={typeface:"Arial",fontSize:opts.size||24,bold:true,color:opts.color||ink,alignment:opts.align||"center",verticalAlignment:"middle",wrap:"none",insets:{left:0,right:0,top:0,bottom:0}};
  return o;
}
function page(title,sub) {
  const s=deck.slides.add();
  s.background.fill="#F8FBFF";
  label(s,"NORTHSTAR  /  RELEASE OPERATIONS",72,40,1100,38,{size:17,align:"left",color:blue});
  label(s,title,72,88,1100,65,{size:46,align:"left"});
  label(s,sub,72,156,1100,42,{size:22,align:"left"});
  return s;
}
function diagram(title,sub,nodes,edges) {
  const s=page(title,sub), by={};
  for (const [id,t,x,y,w=192,geom="roundRect"] of nodes) by[id]=label(s,t,x,y,w,70,{fill:pale,geometry:geom,size:22});
  for (const [a,b,fromSide,toSide] of edges) s.shapes.connect(by[a],by[b],{kind:"straight",fromSide,toSide,line:{style:"solid",fill:blue,width:3},tail:{type:"triangle"}});
  return s;
}
const flow=diagram("Emergency change workflow","Production change requests during the release freeze",[
  ["a","Change intake",85,320],["b","Risk review",335,320],["c","Approved?",585,320,182,"diamond"],["d","Canary deploy",890,230],["e","Return to owner",890,423],["f","Monitor",890,560]
],[["a","b","right","left"],["b","c","right","left"],["c","d","right","left"],["c","e","right","left"],["d","f","right","right"]]);
label(flow,"Yes",770,287,58,27,{size:17}); label(flow,"No",770,396,58,27,{size:17});
diagram("Event processing architecture","Online request path and asynchronous delivery",[
 ["a","Console",72,345],["b","Edge API",303,345],["c","Policy Engine",535,345],["d","Event Bus",770,238],["e","Metrics Store",770,470],["f","Ledger Writer",1000,238]
],[["a","b","right","left"],["b","c","right","left"],["c","d","right","left"],["c","e","right","left"],["d","f","right","left"]]);
diagram("Release organization","Solid connectors indicate direct reporting",[
 ["a","Delivery Director",535,221,210],["b","Platform Lead",290,350],["c","Service Lead",805,350],["d","Runtime Team",150,515],["e","Identity Team",409,515],["f","Support Team",805,515]
],[["a","b","bottom","top"],["a","c","bottom","top"],["b","d","bottom","top"],["b","e","bottom","top"],["c","f","bottom","top"]]);
const sla=page("Escalation service levels","Maximum time from acknowledgement to first update");
const rows=[["Severity","Minutes","Owner"],["SEV-A","12","Runtime"],["SEV-B","36","Identity"],["SEV-C","90","Support"]];
const tbl=sla.tables.add({rows:4,columns:3,left:130,top:255,width:1020,height:295,values:rows});
for(let r=0;r<4;r++) for(let c=0;c<3;c++) {const cell=tbl.getCell(r,c);cell.fill=r===0?"#C1E1F7":"#E9F4FC";cell.text.style={typeface:"Arial",fontSize:24,color:ink,bold:r===0};}
const gantt=page("Release schedule","Four weekly windows for the November rollout");
for(let i=0;i<4;i++) label(gantt,"W"+(i+1),330+i*200,235,200,52,{color:blue});
for(const [i,name,start,end] of [[0,"Discovery",1,2],[1,"Migration",2,3],[2,"Cutover",4,4]]) {
 const y=318+i*90;
 label(gantt,name,94,y,190,55,{align:"left"});
 for(let j=0;j<4;j++) label(gantt,"",330+j*200,y,198,55,{fill:"#E4EEF8"});
 label(gantt,start===end?"W"+start:"W"+start+"–W"+end,330+(start-1)*200,y,(end-start+1)*200-2,55,{fill:blue,color:"#FFFFFF"});
}
diagram("Go-live readiness tree","Evidence required at the release gate",[
 ["a","Go-live readiness",530,220,220],["b","Security",300,362],["c","Reliability",800,362],["d","Access review",300,515],["e","Failover drill",800,515]
],[["a","b","bottom","top"],["a","c","bottom","top"],["b","d","bottom","top"],["c","e","bottom","top"]]);
const bars=page("Incidents by month","Closed production incidents");
bars.charts.add("bar",{title:"Closed production incidents",titlePlacement:"none",position:{left:160,top:220,width:960,height:430},categories:["Aug","Sep","Oct"],series:[{name:"Incidents",values:[24,36,60],fill:blue}],barOptions:{direction:"column",grouping:"clustered"},hasLegend:false,dataLabels:{showValue:true,position:"outEnd"}});
const pie=page("Capacity allocation","Share of planned delivery hours");
pie.charts.add("pie",{title:"Planned delivery hours",titlePlacement:"none",position:{left:145,top:205,width:990,height:465},categories:["Platform","Service","Risk"],series:[{name:"Hours",values:[54,27,19],points:[{idx:0,fill:"#1768A8"},{idx:1,fill:"#14937E"},{idx:2,fill:"#D88725"}]}],hasLegend:true,legend:{position:"right"},dataLabels:{showCategoryName:true,showPercent:true,position:"outEnd"}});
const candidate=process.argv[2];
await (await PresentationFile.exportPptx(deck)).save(candidate);
if(process.env.PPTX_SKILL_DIR && process.argv[3]) {
 const base=process.env.PPTX_SKILL_DIR;
 const {finalizePresentation}=await import(base+"/container_tools/artifact_tool_utils.mjs");
 await finalizePresentation({workspaceDir:process.cwd(),candidatePath:candidate,finalPath:process.argv[3],
 pythonExecutable:process.env.PPTX_PYTHON||"python3",integrityValidatorPath:base+"/container_tools/inspect_presentation_package_integrity.py",layoutValidatorPath:base+"/container_tools/inspect_presentation_layout_geometry.py",
 layoutArgs:["--expected-slide-size-emu","12192000,6858000","--require-native-table-slide","4"],requiredNativeTableOwnerSlides:[4],fontPolicy:{basis:"design",families:["Arial"]},verifyArtifactToolImport:true,materializeLiteralChartWorkbooks:true});
}
