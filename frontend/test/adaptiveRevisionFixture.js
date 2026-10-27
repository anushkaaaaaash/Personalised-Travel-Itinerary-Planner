import {createAdaptiveFixture} from '../tools/adaptiveVisualFixtures.mjs';
import {groundedPreferences} from './groundedPlanningFixture.js';
export const revisionId='33333333-3333-4333-8333-333333333333',requestId='22222222-2222-4222-8222-222222222222',newPlanId='44444444-4444-4444-8444-444444444444';
export function revisionBase(){const fixture=createAdaptiveFixture();fixture.preferences=groundedPreferences;fixture.requestId=requestId;fixture.phase='completed';const page=fixture.snapshot();page.plan.runAllowance=12;return page;}
export function revisionEnvelope(patch={}){const base=revisionBase(),checkpoint=structuredClone(base.sections[0].checkpoint);checkpoint.itinerary.days[1].activities[0].title='A quieter garden visit';return{revision:{id:revisionId,requestId,basePlanId:base.plan.id,targetDate:'2028-01-02',status:'candidate',accepted:false,expiresAt:base.plan.expiresAt,errorCode:null,remainingCreates:11,candidate:{checkpoint,totalSpentCents:base.plan.spentCents,targetDate:'2028-01-02',status:'candidate',accepted:false},acceptedPlanId:null,...patch}};}
export const revisionRow=patch=>revisionEnvelope(patch).revision;
