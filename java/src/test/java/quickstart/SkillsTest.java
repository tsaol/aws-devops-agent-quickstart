package quickstart;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.times;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.Paths;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mockito.ArgumentCaptor;
import org.mockito.Answers;
import software.amazon.awssdk.awscore.exception.AwsErrorDetails;
import software.amazon.awssdk.core.document.Document;
import software.amazon.awssdk.services.devopsagent.DevOpsAgentClient;
import software.amazon.awssdk.services.devopsagent.model.Asset;
import software.amazon.awssdk.services.devopsagent.model.CreateAssetRequest;
import software.amazon.awssdk.services.devopsagent.model.CreateAssetResponse;
import software.amazon.awssdk.services.devopsagent.model.ListAssetsRequest;
import software.amazon.awssdk.services.devopsagent.model.ListAssetsResponse;
import software.amazon.awssdk.services.devopsagent.model.ValidationException;

class SkillsTest {
  static final String S = "00000000-0000-0000-0000-000000000000";
  static final Skills SK = new Skills(Paths.get("..", "tools-for-devops-agent", "skills"));

  static Asset asset(String id, String name) {
    return Asset.builder().assetId(id).assetType("skill").version(1).createdAt(Instant.EPOCH).updatedAt(Instant.EPOCH)
        .metadata(Document.fromMap(Map.of("name", Document.fromString(name)))).build();
  }

  @Test
  void fortySevenSkillsWithValidFrontmatter() {
    List<String> all = SK.all();
    assertEquals(47, all.size());
    for (String s : all) {
      Skills.Frontmatter fm = SK.frontmatter(s);
      assertEquals(s, fm.name());
      assertTrue(Skills.AGENT_TYPES.containsAll(fm.agentTypes()), s);
    }
  }

  @Test
  void zipsHoldOnlyRuntimeFilesWithSkillMdAtRoot() throws IOException {
    for (String s : SK.all()) {
      byte[] data = SK.buildZip(s);
      assertTrue(data.length < Skills.MAX_ZIP, s);
      List<String> names = new ArrayList<>();
      try (ZipInputStream z = new ZipInputStream(new ByteArrayInputStream(data))) {
        for (ZipEntry e; (e = z.getNextEntry()) != null; ) names.add(e.getName());
      }
      assertTrue(names.contains("SKILL.md"), s);
      for (String n : names) assertTrue(Skills.RUNTIME_PARTS.contains(n.split("/")[0]), s + ": " + n);
    }
  }

  @Test
  void allSkipsExamplesAndThirdParty() {
    assertEquals(35, SK.defaults(false, false).size());
    assertEquals(37, SK.defaults(true, false).size());
    assertEquals(47, SK.defaults(true, true).size());
  }

  @Test
  void installSkipsExistingUploadsZipImportsGithubAndKeepsGoingAfterFailure() {
    DevOpsAgentClient c = mock(DevOpsAgentClient.class, Answers.CALLS_REAL_METHODS);
    doReturn(ListAssetsResponse.builder().items(asset("a-0", "other")).nextToken("p2").build())
        .when(c).listAssets(argThat((ListAssetsRequest r) -> r != null && r.nextToken() == null));
    doReturn(ListAssetsResponse.builder().items(asset("a-1", "aws-health-events")).build())
        .when(c).listAssets(argThat((ListAssetsRequest r) -> r != null && "p2".equals(r.nextToken())));
    doThrow(ValidationException.builder().awsErrorDetails(AwsErrorDetails.builder()
            .errorCode("ValidationException").errorMessage("No GitHub access is configured").build()).build())
        .when(c).createAsset(argThat((CreateAssetRequest r) -> r != null && r.content().sourceUrl() != null
            && r.content().sourceUrl().url().endsWith("/aws-routing")));
    doReturn(CreateAssetResponse.builder().asset(asset("a-2", "x")).build())
        .when(c).createAsset(argThat((CreateAssetRequest r) -> r != null && r.content().zip() != null));
    doReturn(CreateAssetResponse.builder().asset(asset("a-3", "x")).build())
        .when(c).createAsset(argThat((CreateAssetRequest r) -> r != null && r.content().sourceUrl() != null
            && r.content().sourceUrl().url().endsWith("/support-cases")));

    List<String> log = new ArrayList<>();
    Map<String, String> r = SK.install(c, S, List.of("aws-health-events", "aws-routing"), false, log::add);
    Map<String, String> want = new LinkedHashMap<>();
    want.put("aws-health-events", "skipped");
    want.put("aws-routing", "a-2");
    assertEquals(want, r);

    r = SK.install(c, S, List.of("aws-routing", "support-cases"), true, log::add);
    want = new LinkedHashMap<>();
    want.put("aws-routing", "failed");
    want.put("support-cases", "a-3");
    assertEquals(want, r);
    assertTrue(String.join("\n", log).contains("FAILED  aws-routing: ValidationException"));

    ArgumentCaptor<CreateAssetRequest> req = ArgumentCaptor.forClass(CreateAssetRequest.class);
    verify(c, times(3)).createAsset(req.capture());
    CreateAssetRequest zip = req.getAllValues().get(0);
    assertEquals("skill", zip.assetType());
    assertEquals(S, zip.agentSpaceId());
    assertEquals(List.of("CHAT", "INCIDENT_RCA"), zip.metadata().asMap().get("agent_types").asList().stream()
        .map(Document::asString).toList());
  }

  @Test
  @EnabledIfEnvironmentVariable(named = "ONLINE", matches = "1")
  void everyGithubSkillUrlOpens() throws IOException {
    List<String> bad = new ArrayList<>();
    for (String s : SK.all()) {
      HttpURLConnection h = (HttpURLConnection) new URL(Skills.GITHUB_TREE + s).openConnection();
      h.setRequestMethod("HEAD");
      if (h.getResponseCode() != 200) bad.add(s + " " + h.getResponseCode());
    }
    assertEquals(List.of(), bad);
  }
}
