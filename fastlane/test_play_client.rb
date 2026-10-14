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
