# Run with bundle exec ruby fastlane/test_play_client.rb. No account or network access.
require "fastlane"
require_relative "play_client"

class FakePublisher
  attr_reader :commits, :details

  def initialize(errors)
    @errors = errors
    @commits = []
    @details = Google::Apis::AndroidpublisherV3::AppDetails.new(
      default_language: "ko-KR", contact_phone: "+82-10-0000-0000")
  end

  def get_edit_detail(*) = @details
  def insert_edit(*) = Google::Apis::AndroidpublisherV3::AppEdit.new(id: "new-upload-edit")
  def update_edit_detail(_, _, details) = @details = details

  def commit_edit(_, _, **options)
    @commits << options
    error = @errors.shift
    raise error if error
  end
end

def check(condition, message)
  raise message unless condition
end

def client_for(publisher)
  client = PlayReleaseClient.allocate
  client.client = publisher
  client.current_package_name = "com.example.app"
  client.current_edit = Google::Apis::AndroidpublisherV3::AppEdit.new(id: "test-edit")
  client.contact_email = "developer@example.com"
  client
end

def api_error(status, message)
  Google::Apis::ClientError.new(message, status_code: status,
                              body: JSON.generate(error: {message: message}))
end

Supply.config = {changes_not_sent_for_review: true}
hold_error = "Changes are sent for review automatically. The query parameter changesNotSentForReview must not be set."
publisher = FakePublisher.new([api_error(400, hold_error), nil])
client = client_for(publisher)
client.allow_automatic_review = true
client.commit_current_edit!
check(publisher.commits.size == 2, "The rejected parameter must cause one commit retry")
check(publisher.commits.all? { |p| p[:changes_in_review_behavior] == "ERROR_IF_IN_REVIEW" }, "Never cancel an existing review")
check(!publisher.commits.last.key?(:changes_not_sent_for_review), "Omit only the rejected parameter")
check(publisher.details.contact_email == "developer@example.com", "Sync the configured support contact")
check(publisher.details.default_language == "ko-KR" && publisher.details.contact_phone == "+82-10-0000-0000", "Preserve existing contact details")
check(client.current_edit.nil?, "Clear the edit after confirmed success")

[[400, "You already have changes in review"], [403, hold_error]].each do |status, message|
  publisher = FakePublisher.new([api_error(status, message)])
  client = client_for(publisher)
  begin
    client.commit_current_edit!
    raise "A rejected review or permission error must be propagated"
  rescue Google::Apis::ClientError
    check(publisher.commits.size == 1, "Do not retry review or permission errors")
    check(!client.current_edit.nil?, "Do not report a failed commit as saved")
  end
end
puts "3 Play commit policy cases passed"

require "ostruct"
class SnapshotPublisher
  attr_reader :deleted
  def initialize(fail_read: false) = @fail_read = fail_read
  def insert_edit(*) = OpenStruct.new(id: "read-edit")
  def delete_edit(_, id) = @deleted = id
  def list_edit_tracks(*)
    raise "read failed" if @fail_read
    OpenStruct.new(tracks: [OpenStruct.new(track: "production", releases: [OpenStruct.new(name: "1.2.3", version_codes: ["51"], status: "completed")])])
  end
  def list_edit_bundles(*) = OpenStruct.new(bundles: [OpenStruct.new(version_code: 51, sha256: "aab-hash")])
  def get_edit_countryavailability(*) = OpenStruct.new(countries: [OpenStruct.new(country_code: "KR")], rest_of_world: true)
  def list_edit_listings(*) = OpenStruct.new(listings: [OpenStruct.new(language: "ko-KR")])
  def list_edit_images(_, _, _, type)
    raise "Unsupported current Publisher image type" unless %w[phoneScreenshots icon featureGraphic tvBanner].include?(type)
    OpenStruct.new(images: [OpenStruct.new(id: "first", sha256: "hash-1"), OpenStruct.new(id: "second", sha256: "hash-2")])
  end
end
publisher = SnapshotPublisher.new
snapshot = PlayReleaseSnapshot.read(publisher, "com.example.app")
check(snapshot[:bundles].first[:sha256] == "aab-hash", "Read uploaded artifact hashes")
check(snapshot[:phone_screenshots]["ko-KR"].map { |i| i[:sha256] } == ["hash-1", "hash-2"], "Preserve remote screenshot order")
check(snapshot[:rest_of_world] && snapshot[:countries] == ["KR"], "Preserve remote country availability")
check(publisher.deleted == "read-edit", "Discard temporary read edit")
publisher = SnapshotPublisher.new(fail_read: true)
begin
  PlayReleaseSnapshot.read(publisher, "com.example.app")
  raise "Read errors must propagate"
rescue RuntimeError => error
  check(error.message == "read failed", "Keep original read error")
  check(publisher.deleted == "read-edit", "Discard edit even after a failed read")
end
puts "2 remote snapshot cases passed"

[["0.1", "inProgress"], ["1.0", "completed"]].each do |fraction, status|
  options = PlayReleaseRollout.options(fraction)
  configuration = FastlaneCore::Configuration.create(Supply::Options.available_options,
    {package_name: "com.example.app", **options})
  check(configuration[:rollout] == fraction, "Supply requires rollout as a string")
  check(configuration[:release_status] == status, "Choose the matching release status")
end
["0", "-0.1", "1.1", "NaN", "Infinity", "bad"].each do |fraction|
  begin
    PlayReleaseRollout.options(fraction)
    raise "An invalid rollout must fail before accessing Play"
  rescue ArgumentError
    # No API call has been made.
  end
end
puts "8 rollout configuration cases passed"

publisher = SnapshotPublisher.new
staged = PlayReleaseSnapshot.read_existing(publisher, "com.example.app", "kept-edit")
check(publisher.deleted.nil?, "Reading a failed edit must preserve it for resumption")
check(staged[:state] == "uncommitted-edit", "Never report staged changes as committed")
expected_images = {"ko-KR" => ["hash-1", "hash-2"]}
rollout = PlayReleaseRollout.options("1.0")
PlayReleaseResume.validate(staged, "com.example.app", 51, "aab-hash", expected_images, rollout)
[["com.other.app", 51, "aab-hash", expected_images, rollout],
 ["com.example.app", 52, "aab-hash", expected_images, rollout],
 ["com.example.app", 51, "wrong-hash", expected_images, rollout],
 ["com.example.app", 51, "aab-hash", {"ko-KR" => ["hash-2", "hash-1"]}, rollout],
 ["com.example.app", 51, "aab-hash", expected_images, PlayReleaseRollout.options("0.1")]].each do |arguments|
  begin
    PlayReleaseResume.validate(staged, *arguments)
    raise "Mismatched staged changes must not be committed"
  rescue ArgumentError
    # Requires the same validated version, artifact, screenshot order and requested rollout.
  end
end
puts "7 preserved-edit and guarded resumption cases passed"
check(PlayReleaseSnapshot.invalid_edit?(api_error(400, "This edit has expired, please create a new Edit.")), "Recognize Google's explicit edit expiry")
check(!PlayReleaseSnapshot.invalid_edit?(api_error(403, "The caller does not have permission")), "Permission errors must preserve the active edit")
check(!PlayReleaseSnapshot.invalid_edit?(api_error(400, "Invalid request")), "An unrelated validation error must not discard an edit")
puts "3 edit expiry classification cases passed"

require "tmpdir"
Dir.mktmpdir do |directory|
  client = PlayReleaseClient.allocate
  client.client = FakePublisher.new([])
  client.edit_status_path = File.join(directory, "receipt.json")
  client.begin_edit(package_name: "com.example.app")
  receipt = JSON.parse(File.read(client.edit_status_path))
  check(receipt == {"package_name" => "com.example.app", "edit_id" => "new-upload-edit", "status" => "uploading"},
        "Save the edit receipt before any binary/metadata upload can fail")
end
puts "1 upload-start receipt case passed"

# Initial Console apps require a saved production draft before their first review.
draft_options = PlayReleaseRollout.promotion_options(release_status: "draft")
configuration = FastlaneCore::Configuration.create(Supply::Options.available_options,
  {package_name: "com.example.app", **draft_options})
check(configuration[:release_status] == "draft" && configuration[:track_promote_release_status] == "draft",
      "Both Supply statuses must remain draft; saving a first release must not publish it")
check(configuration[:rollout].nil?, "Supply forbids rollout fractions for draft promotions")
check(PlayReleaseRollout.promotion_options("0.2") == PlayReleaseRollout.options("0.2"), "Keep existing production rollout behavior")
[["1.0", "draft"], [nil, "unknown"]].each do |value, status|
  begin
    PlayReleaseRollout.promotion_options(value, release_status: status)
    raise "Invalid draft/promotion options must fail before remote access"
  rescue ArgumentError
  end
end
puts "5 initial production draft configuration cases passed"

# A test/draft operation must not silently remove Google's automatic-review hold.
publisher = FakePublisher.new([api_error(400, hold_error)])
client = client_for(publisher)
begin
  client.commit_current_edit!
  raise "Automatic review fallback must be opt-in"
rescue Google::Apis::ClientError
  check(publisher.commits.size == 1, "Do not silently send draft/listing changes for automatic review")
  check(!client.current_edit.nil?, "Keep the rejected edit for inspection")
end
puts "1 explicit automatic-review consent case passed"

require "json"
before = PlayReleaseSnapshot.read(SnapshotPublisher.new, "com.example.app")
rollout = PlayReleaseRollout.options("1.0")
arguments = {package: "com.example.app", track: "production", code: 51,
             sha256: "aab-hash", images: {"ko-KR" => ["hash-1", "hash-2"]}, rollout: rollout}
check(PlayReleaseVerification.validate(before, before, **arguments), "Verify committed release identity")
mutations = [
  ->(s) { s[:state] = "uncommitted-edit" },
  ->(s) { s[:package_name] = "com.other.app" },
  ->(s) { s[:bundles][0][:sha256] = "wrong" },
  ->(s) { s[:countries] = ["US"] },
  ->(s) { s[:rest_of_world] = false },
  ->(s) { s[:phone_screenshots]["ko-KR"].reverse! },
  ->(s) { s[:tracks][0][:releases][0][:version_codes] = ["52"] },
  ->(s) { s[:tracks][0][:releases][0][:status] = "draft" }
]
mutations.each do |mutate|
  after = Marshal.load(Marshal.dump(before))
  mutate.call(after)
  begin
    PlayReleaseVerification.validate(before, after, **arguments)
    raise "A mismatched remote release must fail verification"
  rescue ArgumentError
  end
end
puts "9 post-submission identity verification cases passed"

# A new app with no production track can still prepare/read its internal draft.
class FirstAppPublisher < SnapshotPublisher
  def list_edit_tracks(*) = OpenStruct.new(tracks: [])
  def get_edit_countryavailability(*) = raise Google::Apis::ClientError.new("Not found", status_code: 404)
end
first = PlayReleaseSnapshot.read(FirstAppPublisher.new, "com.example.first")
check(first[:countries].nil? && first[:tracks].empty?, "Do not require a production resource just to read a first app")
puts "1 first-app snapshot case passed"

before_test = Marshal.load(Marshal.dump(before))
after_test = Marshal.load(Marshal.dump(before))
after_test[:tracks] << {track: "internal", releases: [{version_codes: ["52"], status: "draft"}]}
after_test[:bundles] << {version_code: 52, sha256: "test-hash"}
test_args = arguments.merge(track: "internal", code: 52, sha256: "test-hash", rollout: nil)
check(PlayReleaseVerification.validate(before_test, after_test, **test_args), "Internal draft preserves production")
after_test[:tracks][0][:releases][0][:version_codes] = ["52"]
begin
  PlayReleaseVerification.validate(before_test, after_test, **test_args)
  raise "Internal upload must not alter production"
rescue ArgumentError
end
puts "2 internal/production separation cases passed"

internal_stage = Marshal.load(Marshal.dump(staged))
internal_stage[:tracks] = [{track: "internal", releases: [{version_codes: ["51"], status: "draft"}]}]
PlayReleaseResume.validate(internal_stage, "com.example.app", 51, "aab-hash", expected_images, {release_status: "draft"}, track: "internal")
puts "1 guarded internal-draft resumption case passed"
