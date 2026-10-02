import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ResearchPanel from "./research-panel";

const fetch = vi.fn();
const session = {
  schema_version:"research-v1", id:"research-session", state:"pending",
  request:{question:"Synthetic star color?",freshness:"general",idempotency_key:"key"},
  answer:null,failure_code:null,expires_at:"2099-01-01T00:00:00Z",citations:[],attempts:[],
};
const completed = {...session,state:"completed",answer:"The synthetic star is blue. [1]",attempts:[{adapter:"fake"}],citations:[{
  number:1,url:"https://example.org/star",title:"Synthetic source",observed_at:"2026-10-02T00:00:00Z",expires_at:"2099-01-01T00:00:00Z",
}]};
function json(body: unknown) { return new Response(JSON.stringify(body),{headers:{"Content-Type":"application/json"}}); }
function stream() { return new Response(`event: research.terminal\ndata: ${JSON.stringify({schema_version:"research-v1",session_id:session.id,state:"completed"})}\n\n`, {headers:{"Content-Type":"text/event-stream"}}); }
function fill() { fireEvent.change(screen.getByLabelText("Research question"),{target:{value:session.request.question}}); }

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
});
