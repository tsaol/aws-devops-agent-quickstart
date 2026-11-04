package quickstart;

import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;
import software.amazon.awssdk.core.document.Document;
import software.amazon.awssdk.protocols.jsoncore.JsonNode;
import software.amazon.awssdk.services.devopsagent.DevOpsAgentAsyncClient;
import software.amazon.awssdk.services.devopsagent.DevOpsAgentClient;
import software.amazon.awssdk.services.devopsagent.model.CreateBacklogTaskRequest;
import software.amazon.awssdk.services.devopsagent.model.Execution;
import software.amazon.awssdk.services.devopsagent.model.JournalRecord;
import software.amazon.awssdk.services.devopsagent.model.ListExecutionsResponse;
import software.amazon.awssdk.services.devopsagent.model.ListJournalRecordsResponse;
import software.amazon.awssdk.services.devopsagent.model.ListRecommendationsResponse;
import software.amazon.awssdk.services.devopsagent.model.Recommendation;
import software.amazon.awssdk.services.devopsagent.model.SendMessageContentBlockDeltaEvent;
import software.amazon.awssdk.services.devopsagent.model.SendMessageContentBlockStartEvent;
import software.amazon.awssdk.services.devopsagent.model.SendMessageEvents;
import software.amazon.awssdk.services.devopsagent.model.SendMessageResponseFailedEvent;
import software.amazon.awssdk.services.devopsagent.model.SendMessageResponseHandler;
import software.amazon.awssdk.services.devopsagent.model.Task;

/** Ask questions and run investigations with AWS DevOps Agent. */
public final class QuickStart {
  public static final Set<String> DONE =
      Set.of("COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED");
  /** Needs a person: approve or reject the mitigation plan in the Agent Space web app. */
  public static final Set<String> NEEDS_YOU = Set.of("PENDING_CUSTOMER_APPROVAL");

  /**
   * Journal record types worth showing: type -> {title field, body field}. The rest (message,
   * utilization, ui_investigation_summary, ...) is raw model traffic or data for the web UI.
   */
  static final Map<String, String[]> SHOW = Map.of(
      "observation", new String[] {"title", "analysis"},
      "investigation_gap", new String[] {"title", "description"},
      "root_cause", new String[] {"title", "description"},
      "mitigation", new String[] {"title", "description"},
      "investigation_result", new String[] {null, "text"});

  private static final DateTimeFormatter HMS =
      DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneOffset.UTC);

  private QuickStart() {}

  /**
   * Collects the answer from the chat event stream. The stream has several content blocks:
   * thinking, tool_summary, text, final_response, chat_title... Only "text" is the answer.
   * "final_response" repeats it, so it is used only if no "text" block came.
   */
  public static final class ChatAnswer {
    private final Map<Integer, String> blockType = new HashMap<>();
    private final StringBuilder answer = new StringBuilder();
    private final StringBuilder fallback = new StringBuilder();
    private final Consumer<String> write;
    private String error;

    public ChatAnswer(Consumer<String> write) {
      this.write = write;
    }

    public SendMessageResponseHandler.Visitor visitor() {
      return SendMessageResponseHandler.Visitor.builder()
          .onContentBlockStart(this::onStart)
          .onContentBlockDelta(this::onDelta)
          .onResponseFailed(this::onFailed)
          .onDefault(e -> {})
          .build();
    }

    void onStart(SendMessageContentBlockStartEvent e) {
      blockType.put(e.index(), e.type());
    }

    void onDelta(SendMessageContentBlockDeltaEvent e) {
      if (e.delta() == null || e.delta().textDelta() == null) return;
      String t = e.delta().textDelta().text();
      String kind = blockType.get(e.index());
      if (t == null) return;
      if ("text".equals(kind)) {
        answer.append(t);
        write.accept(t);
      } else if ("final_response".equals(kind)) {
        fallback.append(t);
      }
    }

    void onFailed(SendMessageResponseFailedEvent e) {
      error = e.errorMessage();
    }

    /** Feed one event (used by tests; the SDK calls the visitor directly). */
    public void accept(SendMessageEvents event) {
      event.accept(visitor());
    }

    public String finish() {
      if (error != null) throw new IllegalStateException(error);
      if (answer.length() == 0 && fallback.length() > 0) {
        answer.append(fallback);
        write.accept(fallback.toString());
      }
      write.accept("\n");
      return answer.toString();
    }
  }

  /** Chat: one question, stream the answer. SendMessage is an event stream, so it needs the async client. */
  public static String ask(DevOpsAgentClient client, DevOpsAgentAsyncClient async, String space,
      String question, Consumer<String> write) {
    String executionId = client.createChat(r -> r.agentSpaceId(space)).executionId();
    ChatAnswer collector = new ChatAnswer(write);
    AtomicReference<Throwable> streamError = new AtomicReference<>();
    SendMessageResponseHandler handler = SendMessageResponseHandler.builder()
        .subscriber(collector.visitor())
        .onError(streamError::set)
        .build();
    async.sendMessage(r -> r.agentSpaceId(space).executionId(executionId).content(question), handler)
        .join();
    if (streamError.get() != null) throw new IllegalStateException(streamError.get());
    return collector.finish();
  }

  /** Short readable line for a journal record, or null to skip it. content is often a JSON string. */
  public static String recordText(JournalRecord record) {
    String[] keys = SHOW.get(record.recordType());
    if (keys == null) return null;
    Document c = record.content();
    Map<String, JsonNode> obj;
    try {
      String json = c.isString() ? c.asString() : c.toString();
      JsonNode node = JsonNode.parser().parse(json);
      if (!node.isObject()) return record.recordType() + ": " + json;
      obj = node.asObject();
    } catch (RuntimeException e) {
      return record.recordType() + ": " + (c.isString() ? c.asString() : c);
    }
    String title = keys[0] == null ? null : text(obj.get(keys[0]));
    String body = text(obj.get(keys[1]));
    return title != null
        ? record.recordType() + ": " + title + " - " + body
        : record.recordType() + ": " + body;
  }

  private static String text(JsonNode n) {
    return n == null || n.isNull() ? null : n.isString() ? n.asString() : n.toString();
  }

  /** Start an investigation, wait for it, print the steps and recommendations. */
  public static Task investigate(DevOpsAgentClient client, String space, String title,
      String description, long pollMillis, Consumer<String> log) throws InterruptedException {
    long maxWait = Long.parseLong(System.getenv().getOrDefault("MAX_WAIT_MINUTES", "60")) * 60_000;
    return investigate(client, space, title, description, pollMillis, maxWait, log);
  }

  public static Task investigate(DevOpsAgentClient client, String space, String title,
      String description, long pollMillis, long maxWaitMillis, Consumer<String> log)
      throws InterruptedException {
    Task task = client.createBacklogTask(CreateBacklogTaskRequest.builder()
            .agentSpaceId(space).taskType("INVESTIGATION").priority("HIGH")
            .title(title).description(description).build())
        .task();
    String taskId = task.taskId();
    log.accept("task " + taskId + ": " + task.statusAsString());

    long deadline = System.currentTimeMillis() + maxWaitMillis;
    while (!DONE.contains(task.statusAsString()) && !NEEDS_YOU.contains(task.statusAsString())) {
      if (System.currentTimeMillis() > deadline) {
        log.accept("  still " + task.statusAsString() + " after " + maxWaitMillis / 60_000
            + " min, stop waiting (check task " + taskId + " in the web app)");
        break;
      }
      Thread.sleep(pollMillis);
      task = client.getBacklogTask(r -> r.agentSpaceId(space).taskId(taskId)).task();
      log.accept("  status = " + task.statusAsString());
    }
    if (NEEDS_YOU.contains(task.statusAsString())) log.accept("  waiting for your approval in the Agent Space web app");
    if ("LINKED".equals(task.statusAsString())) {
      log.accept("  merged into task " + task.primaryTaskId() + ": "
          + (task.statusReason() == null ? "" : task.statusReason()));
    } else if (task.statusReason() != null) {
      log.accept("  reason: " + task.statusReason());
    }

    // What the agent did: executions -> journal records (all pages)
    List<Execution> executions = new ArrayList<>();
    String token = null;
    do {
      final String t = token;
      ListExecutionsResponse page = client.listExecutions(r -> r.agentSpaceId(space).taskId(taskId).nextToken(t));
      executions.addAll(page.executions());
      token = page.nextToken();
    } while (token != null);

    for (Execution ex : executions) {
      log.accept("\n== execution " + ex.executionId() + " (" + ex.agentSubTask() + ", "
          + ex.executionStatusAsString() + ")");
      String jt = null;
      do {
        final String t = jt;
        ListJournalRecordsResponse page = client.listJournalRecords(q -> q.agentSpaceId(space)
            .executionId(ex.executionId()).order("ASC").nextToken(t));
        for (JournalRecord r : page.records()) {
          String line = recordText(r);
          if (line != null) log.accept("  [" + HMS.format(r.createdAt()) + "] " + line);
        }
        jt = page.nextToken();
      } while (jt != null);
    }

    // What the agent suggests (all pages)
    String rt = null;
    do {
      final String t = rt;
      ListRecommendationsResponse page = client.listRecommendations(r -> r.agentSpaceId(space).taskId(taskId).nextToken(t));
      for (Recommendation rec : page.recommendations()) {
        log.accept("\n* [" + rec.priorityAsString() + "] " + rec.title() + "\n  " + rec.content().summary());
      }
      rt = page.nextToken();
    } while (rt != null);
    return task;
  }
}
