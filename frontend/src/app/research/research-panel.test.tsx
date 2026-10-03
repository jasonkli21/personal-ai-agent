import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ResearchPanel from "./research-panel";

const fetch = vi.fn();
const sessionId = "22222222-2222-4222-8222-222222222222";
const runId = "11111111-1111-4111-8111-111111111111";
const session = {
  schema_version:"research-v1", id:sessionId, state:"pending",
  request:{question:"Synthetic star color?",freshness:"general",idempotency_key:"33333333-3333-4333-8333-333333333333"},
  answer:null,failure_code:null,expires_at:"2099-01-01T00:00:00Z",citations:[],attempts:[],
};
const completed = {...session,state:"completed",answer:"The synthetic star is blue. [1]",attempts:[{adapter:"fake"}],citations:[{
  number:1,evidence_id:"44444444-4444-4444-8444-444444444444",source_observation_id:"55555555-5555-4555-8555-555555555555",url:"https://example.org/star",title:"Synthetic source",observed_at:"2026-10-02T00:00:00Z",expires_at:"2099-01-01T00:00:00Z",
}]};
function json(body: unknown) { return new Response(JSON.stringify(body),{headers:{"Content-Type":"application/json"}}); }
function stream() { return new Response(`event: research.terminal\ndata: ${JSON.stringify({schema_version:"research-v1",session_id:session.id,state:"completed"})}\n\n`, {headers:{"Content-Type":"text/event-stream"}}); }
function fill() { fireEvent.change(screen.getByLabelText("Research question"),{target:{value:session.request.question}}); }
const iterativeSession = {
  ...session, id:"66666666-6666-4666-8666-666666666666", state:"completed", answer:"Partial answer from supported evidence. [1]",
  citations:[{number:1,evidence_id:"77777777-7777-4777-8777-777777777777",source_observation_id:"88888888-8888-4888-8888-888888888888",url:"https://example.org/verified",title:"Verified synthetic source",observed_at:"2026-10-02T00:00:00Z",expires_at:"2099-01-01T00:00:00Z"}],
};
const iterativeRun = {
  schema_version:"iterative-research-v1", id:runId, session_id:iterativeSession.id,state:"insufficient", terminal_reason:"query_budget_exhausted" as string | null,
  current_iteration:1, decision_state:"research_needed", decision_ids:[],
  budget:{max_iterations:3,max_queries:2,max_sources:8,max_elapsed_seconds:90,max_tokens:6000,max_provider_cost_usd:"0.05",allowed_domains:["example.org"]},
  usage:{iterations:2,queries:2,sources:1,tokens:640,provider_cost_usd:"0.004",elapsed_seconds:"12",allowed_domains:1},
  gaps:[
    {semantic_key:"required_fact_missing:price",gap_class:"required_fact_missing",required:true,status:"open",reason_code:"missing_required_claim"},
    {semantic_key:"required_fact_missing:price",gap_class:"required_fact_missing",required:true,status:"open",reason_code:"missing_required_claim"},
  ],
  events:[],
};
function iterativeEvent(sequence:number,eventType:string,state:string) {
  const data={schema_version:"iterative-research-v1",run_id:iterativeRun.id,session_id:iterativeSession.id,sequence,event_type:eventType,state,iteration:sequence,query_count:sequence,source_count:1,gap_count:1};
  return `id: ${sequence}\nevent: research.iterative.${eventType}\ndata: ${JSON.stringify(data)}\n\n`;
}
function iterativeStream(...events:string[]) { return new Response(events.join(""), {headers:{"Content-Type":"text/event-stream"}}); }
function iterativeDetail(run=iterativeRun) { return {run,session:iterativeSession}; }

beforeEach(() => { fetch.mockReset(); vi.stubGlobal("fetch",fetch); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("research page", () => {
  it("shows cited excerpts, freshness and the synthetic demo label", async () => {
    fetch.mockResolvedValueOnce(json(session)).mockResolvedValueOnce(stream()).mockResolvedValueOnce(json(completed));
    render(<ResearchPanel />); fill(); fireEvent.click(screen.getByRole("button",{name:"Research"}));
    expect(await screen.findByText(completed.answer)).toBeInTheDocument();
    expect(screen.getByRole("link",{name:"Synthetic source"})).toHaveAttribute("href","https://example.org/star");
    expect(screen.getByText(/Synthetic demo/)).toBeInTheDocument();
    expect(screen.queryByRole("button",{name:"Inspect research"})).not.toBeInTheDocument();
  });
  it("reuses the creation key after a connection failure", async () => {
    fetch.mockRejectedValueOnce(new Error("offline"));
    render(<ResearchPanel />); fill(); fireEvent.click(screen.getByRole("button",{name:"Research"}));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const first = JSON.parse(fetch.mock.calls[0][1].body);
    fetch.mockResolvedValueOnce(json(session)).mockResolvedValueOnce(stream()).mockResolvedValueOnce(json(completed));
    fireEvent.click(screen.getByRole("button",{name:"Retry request"}));
    await screen.findByText(completed.answer);
    expect(JSON.parse(fetch.mock.calls[1][1].body).idempotency_key).toBe(first.idempotency_key);
  });
  it("prevents duplicate submissions and sends abort on stop", async () => {
    let signal: AbortSignal | undefined;
    fetch.mockImplementation((_url, init) => new Promise((_resolve,reject) => {
      signal=init.signal; signal!.addEventListener("abort",()=>reject(new Error("abort")));
    }));
    render(<ResearchPanel />); fill();
    fireEvent.click(screen.getByRole("button",{name:"Research"}));
    fireEvent.click(screen.getByRole("button",{name:"Research"}));
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button",{name:"Stop"}));
    await screen.findByRole("alert"); expect(signal?.aborted).toBe(true);
  });
  it("reopens expired evidence without displaying its answer", async () => {
    fetch.mockResolvedValueOnce(json({...completed,state:"expired",answer:null,citations:[]}));
    render(<ResearchPanel initialSessionId={session.id} />);
    expect(await screen.findByRole("heading",{name:"Evidence expired"})).toBeInTheDocument();
    expect(screen.queryByText(completed.answer)).not.toBeInTheDocument();
  });
  it("withholds a completed answer whose deadline has passed", async () => {
    fetch.mockResolvedValueOnce(json({...completed,expires_at:"2020-01-01T00:00:00Z"}));
    render(<ResearchPanel initialSessionId={session.id} />);
    await waitFor(()=>expect(screen.getByRole("heading",{name:"Evidence expired"})).toBeInTheDocument());
    expect(screen.queryByText(completed.answer)).not.toBeInTheDocument();
  });
  it("keeps single-pass as the default and renders a bounded partial result with every visible gap", async () => {
    fetch.mockResolvedValueOnce(iterativeStream(
      iterativeEvent(0,"planning","planning"),
      iterativeEvent(1,"incomplete","insufficient"),
    )).mockResolvedValueOnce(json(iterativeDetail()));
    render(<ResearchPanel iterativeEnabled />); fill();
    expect(screen.getByLabelText("Research mode")).toHaveValue("single");
    fireEvent.change(screen.getByLabelText("Research mode"),{target:{value:"iterative"}});
    fireEvent.click(screen.getByRole("button",{name:"Start bounded research"}));

    expect(await screen.findByText(iterativeSession.answer)).toBeInTheDocument();
    expect(screen.getByRole("heading",{name:"Incomplete research"})).toBeInTheDocument();
    expect(screen.getByText(/Stop reason: query_budget_exhausted/)).toBeInTheDocument();
    expect(screen.getByText(/Decision status: research_needed/)).toBeInTheDocument();
    expect(screen.getByText(/required fact missing — open \(required\)/)).toBeInTheDocument();
    expect(screen.getByRole("link",{name:"Verified synthetic source"})).toHaveAttribute("href","https://example.org/verified");
    expect(screen.getByLabelText("Research timeline").querySelectorAll("li")).toHaveLength(2);
    expect(fetch.mock.calls[0][0]).toBe("/api/research/iterative");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({schema_version:"iterative-research-request-v1",question:session.request.question});
  });
  it("reconnects by reading saved progress, then sends cancellation through the explicit route", async () => {
    const active={...iterativeRun,state:"searching",terminal_reason:null};
    const cancelled={...iterativeRun,state:"cancelled",terminal_reason:"cancelled"};
    fetch.mockResolvedValueOnce(json(iterativeDetail(active)))
      .mockResolvedValueOnce(iterativeStream(iterativeEvent(0,"searching","searching")))
      .mockResolvedValueOnce(json(cancelled))
      .mockResolvedValueOnce(json(iterativeDetail(cancelled)));
    render(<ResearchPanel initialRunId={active.id} iterativeEnabled />);
    expect(await screen.findByRole("button",{name:"Cancel research"})).toBeInTheDocument();
    expect(screen.getByLabelText("Research timeline").querySelectorAll("li")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button",{name:"Cancel research"}));
    await waitFor(()=>expect(screen.getByRole("heading",{name:"Research cancelled"})).toBeInTheDocument());
    expect(fetch.mock.calls[2][0]).toBe(`/api/research/iterative/runs/${active.id}/cancel`);
    expect(fetch.mock.calls[2][1].method).toBe("POST");
    expect(fetch.mock.calls[1][0]).toContain("/events?after=-1");
  });
  it("exposes explicit cancel as soon as the active run ID arrives on SSE", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const activeStream = new Response(new ReadableStream<Uint8Array>({
      start(value) {
        controller = value;
        value.enqueue(new TextEncoder().encode(iterativeEvent(0,"searching","searching")));
      },
    }), {headers:{"Content-Type":"text/event-stream"}});
    const cancelled={...iterativeRun,state:"cancelled",terminal_reason:"cancelled"};
    const cancelledDetail={run:cancelled,session:{...iterativeSession,state:"insufficient",answer:null,citations:[]}};
    fetch.mockImplementation((url:string,init?:RequestInit) => {
      if(url==="/api/research/iterative") return Promise.resolve(activeStream);
      if(url.endsWith("/cancel")) return Promise.resolve(json(cancelled));
      if(url.endsWith(`/runs/${runId}`)) return Promise.resolve(json(cancelledDetail));
      throw new Error(`Unexpected request ${url} ${init?.method ?? "GET"}`);
    });
    render(<ResearchPanel iterativeEnabled />); fill();
    fireEvent.change(screen.getByLabelText("Research mode"),{target:{value:"iterative"}});
    fireEvent.click(screen.getByRole("button",{name:"Start bounded research"}));

    fireEvent.click(await screen.findByRole("button",{name:"Cancel research"}));
    expect(await screen.findByRole("heading",{name:"Research cancelled"})).toBeInTheDocument();
    expect(fetch.mock.calls[1][0]).toBe(`/api/research/iterative/runs/${runId}/cancel`);
    controller.enqueue(new TextEncoder().encode(iterativeEvent(1,"cancelled","cancelled")));
    controller.close();
    await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(3));
  });
});
