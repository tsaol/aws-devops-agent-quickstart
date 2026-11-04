package quickstart;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Answers;
import software.amazon.awssdk.core.document.Document;
import software.amazon.awssdk.services.devopsagent.DevOpsAgentClient;
import software.amazon.awssdk.services.devopsagent.model.CreateBacklogTaskRequest;
import software.amazon.awssdk.services.devopsagent.model.CreateBacklogTaskResponse;
import software.amazon.awssdk.services.devopsagent.model.Execution;
import software.amazon.awssdk.services.devopsagent.model.GetBacklogTaskRequest;
import software.amazon.awssdk.services.devopsagent.model.GetBacklogTaskResponse;
import software.amazon.awssdk.services.devopsagent.model.JournalRecord;
import software.amazon.awssdk.services.devopsagent.model.ListExecutionsRequest;
import software.amazon.awssdk.services.devopsagent.model.ListExecutionsResponse;
import software.amazon.awssdk.services.devopsagent.model.ListJournalRecordsRequest;
import software.amazon.awssdk.services.devopsagent.model.ListJournalRecordsResponse;
import software.amazon.awssdk.services.devopsagent.model.ListRecommendationsRequest;
import software.amazon.awssdk.services.devopsagent.model.ListRecommendationsResponse;
import software.amazon.awssdk.services.devopsagent.model.Recommendation;
import software.amazon.awssdk.services.devopsagent.model.SendMessageEvents;
import software.amazon.awssdk.services.devopsagent.model.Task;

class QuickStartTest {
  static final String S = "00000000-0000-0000-0000-000000000000";
  static final String EX = "e0000000-0000-4000-8000-000000000001";
  static final Instant NOW = Instant.parse("2026-11-04T14:05:00Z");

  static Task task(String status) {
    return Task.builder().agentSpaceId(S).taskId("t-1").title("5xx spike").taskType("INVESTIGATION")
        .priority("HIGH").status(status).createdAt(NOW).updatedAt(NOW).version(1).build();
  }

  static SendMessageEvents start(int i, String type) {
    return SendMessageEvents.contentBlockStartBuilder().index(i).type(type).build();
  }

  static SendMessageEvents delta(int i, String text) {
    return SendMessageEvents.contentBlockDeltaBuilder().index(i).delta(d -> d.textDelta(t -> t.text(text))).build();
  }

  @Test
  void chatPrintsOnlyTheTextBlock() {
    StringBuilder out = new StringBuilder();
    QuickStart.ChatAnswer a = new QuickStart.ChatAnswer(out::append);
    for (SendMessageEvents e : List.of(
        SendMessageEvents.responseCreatedBuilder().responseId("x").build(),
        start(0, "thinking"), delta(0, "I should check alarms"),
        start(1, "tool_summary"), delta(1, "Done"),
        start(2, "text"), delta(2, "Yes, "), delta(2, "3 alarms."),
        start(3, "final_response"), delta(3, "Yes, 3 alarms."),
        start(4, "chat_title"), delta(4, "Alarm check"),
        SendMessageEvents.responseCompletedBuilder().responseId("x").build())) {
      a.accept(e);
    }
    assertEquals("Yes, 3 alarms.", a.finish());
    assertEquals("Yes, 3 alarms.\n", out.toString());
  }

  @Test
  void chatFallsBackToFinalResponse() {
    StringBuilder out = new StringBuilder();
    QuickStart.ChatAnswer a = new QuickStart.ChatAnswer(out::append);
    a.accept(start(0, "final_response"));
    a.accept(delta(0, "27"));
    assertEquals("27", a.finish());
  }

  @Test
  void chatFailureThrows() {
    QuickStart.ChatAnswer a = new QuickStart.ChatAnswer(t -> {});
    a.accept(SendMessageEvents.responseFailedBuilder().responseId("x").errorMessage("quota exceeded").build());
    assertThrows(IllegalStateException.class, a::finish);
  }

  @Test
  void recordTextParsesJsonStringAndSkipsNoise() {
    JournalRecord obs = JournalRecord.builder().recordType("observation").createdAt(NOW)
        .content(Document.fromString("{\"title\": \"SG 规则被删\", \"analysis\": \"lost port 443\"}")).build();
    JournalRecord util = JournalRecord.builder().recordType("utilization").createdAt(NOW)
        .content(Document.fromString("{\"data\": {}}")).build();
    JournalRecord res = JournalRecord.builder().recordType("investigation_result").createdAt(NOW)
        .content(Document.fromString("{\"text\": \"根因：443 端口规则被删除\"}")).build();
    assertEquals("observation: SG 规则被删 - lost port 443", QuickStart.recordText(obs));
    assertNull(QuickStart.recordText(util));
    assertEquals("investigation_result: 根因：443 端口规则被删除", QuickStart.recordText(res));
  }

  @Test
  void investigatePollsUntilDoneAndPrintsUsefulLines() throws Exception {
    DevOpsAgentClient c = mock(DevOpsAgentClient.class, Answers.CALLS_REAL_METHODS);
    doReturn(CreateBacklogTaskResponse.builder().task(task("PENDING_START")).build())
        .when(c).createBacklogTask(any(CreateBacklogTaskRequest.class));
    doReturn(GetBacklogTaskResponse.builder().task(task("WAITING")).build(),
        GetBacklogTaskResponse.builder().task(task("IN_PROGRESS")).build(),
        GetBacklogTaskResponse.builder().task(task("COMPLETED")).build())
        .when(c).getBacklogTask(any(GetBacklogTaskRequest.class));
    doReturn(ListExecutionsResponse.builder().executions(Execution.builder().executionId(EX)
        .agentSubTask("oncall").executionStatus("STOPPED").build()).build())
        .when(c).listExecutions(any(ListExecutionsRequest.class));
    // two pages each; the conclusion and one recommendation are on page 2
    doReturn(ListJournalRecordsResponse.builder().nextToken("j2").records(
        JournalRecord.builder().recordType("observation").createdAt(NOW)
            .content(Document.fromString("{\"title\": \"SG 规则被删\", \"analysis\": \"lost port 443\"}")).build(),
        JournalRecord.builder().recordType("utilization").createdAt(NOW)
            .content(Document.fromString("{}")).build()).build())
        .when(c).listJournalRecords(argThat((ListJournalRecordsRequest r) -> r != null && r.nextToken() == null));
    doReturn(ListJournalRecordsResponse.builder().records(
        JournalRecord.builder().recordType("investigation_result").createdAt(NOW)
            .content(Document.fromString("{\"text\": \"根因：443 端口规则被删除\"}")).build()).build())
        .when(c).listJournalRecords(argThat((ListJournalRecordsRequest r) -> r != null && "j2".equals(r.nextToken())));
    doReturn(ListRecommendationsResponse.builder().nextToken("r2").recommendations(Recommendation.builder()
        .title("Restore SG rule").priority("HIGH").content(r -> r.summary("Re-add inbound 443")).build()).build())
        .when(c).listRecommendations(argThat((ListRecommendationsRequest r) -> r != null && r.nextToken() == null));
    doReturn(ListRecommendationsResponse.builder().recommendations(Recommendation.builder()
        .title("Add an alarm").priority("MEDIUM").content(r -> r.summary("Alarm on 5xx")).build()).build())
        .when(c).listRecommendations(argThat((ListRecommendationsRequest r) -> r != null && "r2".equals(r.nextToken())));

    List<String> lines = new ArrayList<>();
    Task t = QuickStart.investigate(c, S, "5xx spike", "ALB 5xx > 5%", 0, lines::add);
    String out = String.join("\n", lines);

    assertEquals("COMPLETED", t.statusAsString());
    verify(c, times(3)).getBacklogTask(any(GetBacklogTaskRequest.class));
    ArgumentCaptor<CreateBacklogTaskRequest> req = ArgumentCaptor.forClass(CreateBacklogTaskRequest.class);
    verify(c).createBacklogTask(req.capture());
    assertEquals("INVESTIGATION", req.getValue().taskTypeAsString());
    assertEquals(S, req.getValue().agentSpaceId());
    ArgumentCaptor<ListJournalRecordsRequest> jr = ArgumentCaptor.forClass(ListJournalRecordsRequest.class);
    verify(c, times(2)).listJournalRecords(jr.capture());
    assertEquals("ASC", jr.getAllValues().get(0).orderAsString());
    assertTrue(out.contains("investigation_result: 根因：443 端口规则被删除"), out);
    assertTrue(out.contains("Add an alarm"), out);
    assertTrue(out.contains("status = WAITING"), out);
    assertTrue(out.contains("[14:05:00] observation: SG 规则被删 - lost port 443"), out);
    assertFalse(out.contains("utilization"), out);
    assertTrue(out.contains("[HIGH] Restore SG rule"), out);
  }

  static DevOpsAgentClient shortFlow(Task last) {
    DevOpsAgentClient c = mock(DevOpsAgentClient.class, Answers.CALLS_REAL_METHODS);
    doReturn(CreateBacklogTaskResponse.builder().task(task("PENDING_START")).build())
        .when(c).createBacklogTask(any(CreateBacklogTaskRequest.class));
    doReturn(GetBacklogTaskResponse.builder().task(last).build()).when(c).getBacklogTask(any(GetBacklogTaskRequest.class));
    doReturn(ListExecutionsResponse.builder().build()).when(c).listExecutions(any(ListExecutionsRequest.class));
    doReturn(ListRecommendationsResponse.builder().build()).when(c).listRecommendations(any(ListRecommendationsRequest.class));
    return c;
  }

  @Test
  void approvalLinkedAndTimeout() throws Exception {
    List<String> lines = new ArrayList<>();
    Task t = QuickStart.investigate(shortFlow(task("PENDING_CUSTOMER_APPROVAL")), S, "x", "y", 0, 60_000, lines::add);
    assertEquals("PENDING_CUSTOMER_APPROVAL", t.statusAsString());
    assertTrue(String.join("\n", lines).contains("approval"), lines.toString());

    lines.clear();
    Task linked = task("LINKED").toBuilder().primaryTaskId("t-0").statusReason("same alarm as t-0").build();
    QuickStart.investigate(shortFlow(linked), S, "x", "y", 0, 60_000, lines::add);
    assertTrue(String.join("\n", lines).contains("merged into task t-0: same alarm as t-0"), lines.toString());

    lines.clear();
    t = QuickStart.investigate(shortFlow(task("IN_PROGRESS")), S, "x", "y", 0, -1, lines::add);
    assertEquals("PENDING_START", t.statusAsString());
    assertTrue(String.join("\n", lines).contains("stop waiting"), lines.toString());
  }

  @Test
  void recordTextEdgeCases() {
    JournalRecord notJson = JournalRecord.builder().recordType("investigation_result").createdAt(NOW)
        .content(Document.fromString("not json")).build();
    JournalRecord array = JournalRecord.builder().recordType("investigation_result").createdAt(NOW)
        .content(Document.fromString("[1, 2]")).build();
    assertEquals("investigation_result: not json", QuickStart.recordText(notJson));
    assertEquals("investigation_result: [1, 2]", QuickStart.recordText(array));
  }

  @Test
  void doneStates() {
    for (String s : List.of("COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED")) {
      assertTrue(QuickStart.DONE.contains(s), s);
    }
    assertFalse(QuickStart.DONE.contains("WAITING"));
    assertTrue(QuickStart.NEEDS_YOU.contains("PENDING_CUSTOMER_APPROVAL"));
  }
}
